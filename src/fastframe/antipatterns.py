"""Detection and LibCST rewrites for FastFrame anti-patterns.

The module intentionally deals in source strings rather than importing pandas.  This
makes it suitable for a future CLI and keeps analysis deterministic and offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import libcst as cst
from libcst import matchers as m


@dataclass(frozen=True)
class Finding:
    """A source location and stable identifier for an anti-pattern."""

    pattern: str
    line: int
    column: int
    message: str
    # AP006 is intentionally advisory: its estimate is a per-row estimate when
    # the source does not provide a row count.  ``None`` keeps old consumers
    # source-compatible for the first five patterns.
    estimate_bytes: Optional[int] = None
    manual_fix: bool = False

    @property
    def kind(self) -> str:
        """Alias useful to consumers that call detections ``kind``."""
        return self.pattern

    @property
    def pattern_id(self) -> str:
        return self.pattern


PATTERN_MESSAGES = {
    "AP001": "row-wise DataFrame.apply arithmetic",
    "AP002": "Series.apply arithmetic lambda",
    "AP003": "iterrows arithmetic append-to-list",
    "AP004": "growing DataFrame with concat/append in a loop",
    "AP005": "growing NumPy array with np.append in a loop",
    "AP006": "downcastable object/int64/float64 column (manual review)",
}


def _attribute(call: cst.Call, name: str) -> Optional[cst.Attribute]:
    if isinstance(call.func, cst.Attribute) and call.func.attr.value == name:
        return call.func
    return None


def _lambda(call: cst.Call) -> Optional[cst.Lambda]:
    if not call.args or not isinstance(call.args[0].value, cst.Lambda):
        return None
    return call.args[0].value


def _lambda_param(node: cst.Lambda) -> Optional[str]:
    if len(node.params.params) != 1 or not isinstance(node.params.params[0].name, cst.Name):
        return None
    return node.params.params[0].name.value


def _has_arithmetic(node: cst.CSTNode) -> bool:
    finder = _ArithmeticFinder()
    node.visit(finder)
    return bool(finder.nodes)


class _ArithmeticFinder(cst.CSTVisitor):
    def __init__(self) -> None:
        self.nodes: List[cst.BinaryOperation] = []

    def visit_BinaryOperation(self, node: cst.BinaryOperation) -> None:
        self.nodes.append(node)


def _row_subscript(node: cst.CSTNode, row: str) -> bool:
    finder = _SubscriptFinder()
    node.visit(finder)
    return any(
        isinstance(x, cst.Subscript)
        and isinstance(x.value, cst.Name)
        and x.value.value == row
        for x in finder.nodes
    )


class _SubscriptFinder(cst.CSTVisitor):
    def __init__(self) -> None:
        self.nodes: List[cst.Subscript] = []

    def visit_Subscript(self, node: cst.Subscript) -> None:
        self.nodes.append(node)


def _axis_one(call: cst.Call) -> bool:
    return any(
        arg.keyword and arg.keyword.value == "axis" and isinstance(arg.value, cst.Integer) and arg.value.value == "1"
        for arg in call.args
    )


class _NameReplace(cst.CSTTransformer):
    def __init__(self, name: str, replacement: cst.BaseExpression) -> None:
        self.name, self.replacement = name, replacement

    def leave_Subscript(self, original: cst.Subscript, updated: cst.Subscript) -> cst.BaseExpression:
        if isinstance(original.value, cst.Name) and original.value.value == self.name:
            return updated.with_changes(value=self.replacement)
        return updated

    def leave_Name(self, original: cst.Name, updated: cst.Name) -> cst.BaseExpression:
        # AP002 allows arithmetic such as ``x * 2``.  Subscript bases are handled
        # above, so replacing remaining references gives the expected vectorized op.
        if original.value == self.name:
            return self.replacement
        return updated


def _replace(node: cst.BaseExpression, name: str, replacement: cst.BaseExpression) -> cst.BaseExpression:
    return node.visit(_NameReplace(name, replacement))


class _Detector(cst.CSTVisitor):
    def __init__(self, module: cst.Module) -> None:
        self.module, self.findings = module, []

    def _add(self, node: cst.CSTNode, pattern: str) -> None:
        pos = self.module.code_for_node(node)
        # Metadata-free CST nodes do not expose positions.  The module helper is
        # deterministic; line/column are filled by the transformer wrapper below.
        self.findings.append((node, pattern, pos))

    def visit_Call(self, node: cst.Call) -> None:
        attr = _attribute(node, "apply")
        lam = _lambda(node)
        if attr and lam and _axis_one(node):
            p = _lambda_param(lam)
            if p and _has_arithmetic(lam.body) and _row_subscript(lam.body, p):
                self._add(node, "AP001")
        elif attr and lam:
            p = _lambda_param(lam)
            if p and _has_arithmetic(lam.body) and _has_name(lam.body, p):
                self._add(node, "AP002")
        if _attribute(node, "astype") and _downcast_dtype(node):
            self._add(node, "AP006")

    def visit_For(self, node: cst.For) -> None:
        loop_finding = _loop_growth(node)
        if loop_finding:
            self._add(node, loop_finding)
            # A growth loop is not an iterrows arithmetic loop, even if the
            # body happens to contain an append call.
            return
        if not isinstance(node.iter, cst.Call) or not _attribute(node.iter, "iterrows"):
            return
        if not isinstance(node.target, cst.Tuple) or len(node.target.elements) != 2:
            return
        row = node.target.elements[1].value
        if not isinstance(row, cst.Name) or not isinstance(node.body, cst.IndentedBlock) or len(node.body.body) != 1:
            return
        stmt = node.body.body[0]
        if isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1 and isinstance(stmt.body[0], cst.Expr):
            expr = stmt.body[0].value
            if isinstance(expr, cst.Call) and isinstance(expr.func, cst.Attribute) and expr.func.attr.value == "append" and expr.args:
                if _has_arithmetic(expr.args[0].value) and _row_subscript(expr.args[0].value, row.value):
                    self._add(node, "AP003")

class _NameFinder(cst.CSTVisitor):
    def __init__(self) -> None:
        self.nodes: List[cst.Name] = []

    def visit_Name(self, node: cst.Name) -> None:
        self.nodes.append(node)


def _has_name(node: cst.CSTNode, name: str) -> bool:
    finder = _NameFinder()
    node.visit(finder)
    return any(item.value == name for item in finder.nodes)


def _literal_text(node: cst.CSTNode) -> Optional[str]:
    if not isinstance(node, cst.SimpleString):
        return None
    return node.value[1:-1] if len(node.value) >= 2 else node.value


def _downcast_dtype(call: cst.Call) -> bool:
    for arg in call.args:
        value = arg.value
        if _literal_text(value) in {"object", "int64", "float64"}:
            return True
        if isinstance(value, cst.Dict):
            for element in value.elements:
                if isinstance(element, cst.DictElement) and _literal_text(element.value) in {"object", "int64", "float64"}:
                    return True
    return False


def _downcast_saving(call: cst.Call) -> int:
    """Conservative bytes saved per value for a suggested narrower dtype."""
    for arg in call.args:
        text = _literal_text(arg.value)
        if text == "object":
            return 8
        if text in {"int64", "float64"}:
            return 4
        if isinstance(arg.value, cst.Dict):
            for element in arg.value.elements:
                if isinstance(element, cst.DictElement):
                    text = _literal_text(element.value)
                    if text == "object":
                        return 8
                    if text in {"int64", "float64"}:
                        return 4
    return 0


def _assignment_growth(stmt: cst.CSTNode) -> Optional[Tuple[str, str, cst.Call]]:
    if not (isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1):
        return None
    item = stmt.body[0]
    if not isinstance(item, cst.Assign) or len(item.targets) != 1 or not isinstance(item.value, cst.Call):
        return None
    target_node = item.targets[0].target
    call = item.value
    if not isinstance(target_node, cst.Name) or not isinstance(call.func, cst.Attribute):
        return None
    target, owner, method = target_node.value, call.func.value, call.func.attr.value
    if method == "append" and isinstance(owner, cst.Name) and owner.value == target:
        return target, "append", call
    if method == "append" and isinstance(owner, cst.Name) and owner.value == "np":
        return target, "np.append", call
    if method == "concat" and isinstance(owner, cst.Name) and owner.value == "pd":
        return target, "pd.concat", call
    return None


def _loop_growth(node: cst.For) -> Optional[str]:
    if not isinstance(node.body, cst.IndentedBlock) or len(node.body.body) != 1:
        return None
    growth = _assignment_growth(node.body.body[0])
    return "AP005" if growth and growth[1] == "np.append" else ("AP004" if growth else None)


def detect(source: str) -> List[Finding]:
    """Return anti-patterns in source order, without executing user code."""
    module = cst.parse_module(source)
    detector = _Detector(module)
    module.visit(detector)
    result = []
    for node, pattern, snippet in detector.findings:
        line = source.count("\n", 0, source.find(snippet)) + 1
        column = (source.find(snippet) - (source.rfind("\n", 0, source.find(snippet)) + 1))
        estimate = _downcast_saving(node) if pattern == "AP006" else None
        result.append(Finding(pattern, line, column, PATTERN_MESSAGES[pattern], estimate, pattern == "AP006"))
    return result


class _Rewriter(cst.CSTTransformer):
    def leave_Call(self, original: cst.Call, updated: cst.Call) -> cst.BaseExpression:
        attr = _attribute(original, "apply")
        lam = _lambda(original)
        if not attr or not lam or not _has_arithmetic(lam.body):
            return updated
        p = _lambda_param(lam)
        if not p:
            return updated
        if _axis_one(original) and _row_subscript(lam.body, p):
            return _replace(lam.body, p, attr.value)
        if not _axis_one(original) and _has_name(lam.body, p):
            return _replace(lam.body, p, attr.value)
        return updated

    def leave_For(self, original: cst.For, updated: cst.For) -> cst.BaseStatement:
        growth = _loop_growth(original)
        if growth:
            extracted = _assignment_growth(original.body.body[0])  # type: ignore[union-attr]
            assert extracted is not None
            target, kind, call = extracted
            piece: Optional[cst.BaseExpression] = None
            if kind == "pd.concat" and call.args and isinstance(call.args[0].value, cst.List):
                values = [e.value for e in call.args[0].value.elements if isinstance(e, cst.Element)]
                if len(values) >= 2:
                    piece = values[1]
            elif call.args:
                piece = call.args[0].value if kind == "append" else (call.args[1].value if len(call.args) > 1 else None)
            if piece is None:
                return updated
            # Derive a stable, collision-resistant accumulator name.  Using a
            # single global name would make two independent growth loops share
            # state and silently change results.
            name = f"_fastframe_{target}_parts"
            if growth == "AP004":
                # Keep concat keyword options (notably ignore_index) while
                # replacing only its growing list argument.
                options = ", " + ", ".join(self._code(arg) for arg in call.args[1:]) if len(call.args) > 1 else ""
                suffix = f"pd.concat({name}{options})"
            else:
                suffix = f"np.concatenate({name})"
            append_stmt = cst.parse_statement(f"{name}.append({self._code(piece)})\n")
            loop = updated.with_changes(body=cst.IndentedBlock(body=(append_stmt,)))
            init = cst.parse_statement(f"{name} = [{target}]\n")
            final = cst.parse_statement(f"{target} = {suffix}\n")
            return cst.FlattenSentinel((init, loop, final))
        if not isinstance(original.iter, cst.Call) or not _attribute(original.iter, "iterrows"):
            return updated
        if not isinstance(original.target, cst.Tuple) or len(original.target.elements) != 2 or not isinstance(original.target.elements[1].value, cst.Name):
            return updated
        row = original.target.elements[1].value.value
        frame = original.iter.func.value
        if not isinstance(original.body, cst.IndentedBlock) or len(original.body.body) != 1:
            return updated
        stmt = original.body.body[0]
        if not (isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1 and isinstance(stmt.body[0], cst.Expr)):
            return updated
        expr = stmt.body[0].value
        if not (isinstance(expr, cst.Call) and isinstance(expr.func, cst.Attribute) and expr.func.attr.value == "append" and expr.args):
            return updated
        value = expr.args[0].value
        if not (_has_arithmetic(value) and _row_subscript(value, row)):
            return updated
        vector = _replace(value, row, frame)
        replacement = cst.parse_statement(
            f"{self._code(expr.func.value)}.extend(({self._code(vector)}).tolist())\n"
        )
        return replacement

    @staticmethod
    def _code(node: cst.CSTNode) -> str:
        return cst.Module([]).code_for_node(node)


def rewrite(source: str) -> str:
    """Rewrite all supported anti-patterns in one deterministic LibCST pass."""
    return cst.parse_module(source).visit(_Rewriter()).code


rewrite_source = rewrite
detect_antipatterns = detect
