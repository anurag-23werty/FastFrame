"""Conservative detection and rewrites for FastFrame anti-patterns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


@dataclass(frozen=True)
class Finding:
    pattern: str
    line: int
    column: int
    message: str
    estimate_bytes: Optional[int] = None
    manual_fix: bool = False

    @property
    def kind(self) -> str:
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


def _attr(node: cst.CSTNode, name: str) -> Optional[cst.Attribute]:
    return node if isinstance(node, cst.Attribute) and node.attr.value == name else None


def _call_attr(call: cst.Call, name: str) -> Optional[cst.Attribute]:
    return _attr(call.func, name)


def _lambda(call: cst.Call) -> Optional[cst.Lambda]:
    return call.args[0].value if call.args and isinstance(call.args[0].value, cst.Lambda) else None


def _param(lam: cst.Lambda) -> Optional[str]:
    return lam.params.params[0].name.value if len(lam.params.params) == 1 and isinstance(lam.params.params[0].name, cst.Name) else None


def _string(node: cst.CSTNode) -> bool:
    return isinstance(node, cst.SimpleString)


def _number(node: cst.CSTNode) -> bool:
    return isinstance(node, (cst.Integer, cst.Float))


_OPS = (cst.Add, cst.Subtract, cst.Multiply, cst.Divide, cst.FloorDivide, cst.Power, cst.Modulo)


def _safe_expr(node: cst.CSTNode, name: str, *, allow_bare: bool, require_subscript: bool = False) -> bool:
    """Accept only the small arithmetic language whose vectorization is known safe."""
    if _number(node):
        return True
    if isinstance(node, cst.Name):
        return allow_bare and node.value == name
    if isinstance(node, cst.UnaryOperation):
        return isinstance(node.operator, cst.Minus) and _safe_expr(node.expression, name, allow_bare=allow_bare)
    if isinstance(node, cst.BinaryOperation):
        return isinstance(node.operator, _OPS) and _safe_expr(node.left, name, allow_bare=allow_bare) and _safe_expr(node.right, name, allow_bare=allow_bare)
    if isinstance(node, cst.Subscript):
        return (
            isinstance(node.value, cst.Name)
            and node.value.value == name
            and len(node.slice) == 1
            and isinstance(node.slice[0], cst.SubscriptElement)
            and isinstance(node.slice[0].slice, cst.Index)
            and _string(node.slice[0].slice.value)
        )
    return False


def _receiver_safe(receiver: cst.CSTNode) -> bool:
    class BannedReceiver(cst.CSTVisitor):
        banned = {"groupby", "rolling", "resample", "expanding", "ewm"}

        def __init__(self) -> None:
            self.found = False

        def visit_Attribute(self, node: cst.Attribute) -> None:
            if node.attr.value in self.banned:
                self.found = True

    visitor = BannedReceiver()
    receiver.visit(visitor)
    return not visitor.found


def _axis_one(call: cst.Call) -> bool:
    return any(a.keyword and a.keyword.value == "axis" and isinstance(a.value, cst.Integer) and a.value.value == "1" for a in call.args)


def _replace(node: cst.BaseExpression, name: str, replacement: cst.BaseExpression) -> cst.BaseExpression:
    class Replace(cst.CSTTransformer):
        def leave_Subscript(self, original: cst.Subscript, updated: cst.Subscript) -> cst.BaseExpression:
            if isinstance(original.value, cst.Name) and original.value.value == name:
                return updated.with_changes(value=replacement)
            return updated

        def leave_Name(self, original: cst.Name, updated: cst.Name) -> cst.BaseExpression:
            return replacement if original.value == name else updated

    return node.visit(Replace())


def _literal_text(node: cst.CSTNode) -> Optional[str]:
    return node.value[1:-1] if isinstance(node, cst.SimpleString) and len(node.value) >= 2 else None


def _downcast_dtype(call: cst.Call) -> bool:
    for arg in call.args:
        if _literal_text(arg.value) in {"object", "int64", "float64"}:
            return True
        if isinstance(arg.value, cst.Dict):
            if any(isinstance(e, cst.DictElement) and _literal_text(e.value) in {"object", "int64", "float64"} for e in arg.value.elements):
                return True
    return False


def _downcast_saving(call: cst.Call) -> int:
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


class Rule:
    id: str
    title: str
    explanation: str

    def match(self, node: cst.CSTNode) -> bool:
        raise NotImplementedError

    def rewrite(self, node: cst.CSTNode) -> Optional[cst.CSTNode]:
        return None


class ApplyRule(Rule):
    id = "AP002"
    title = PATTERN_MESSAGES[id]
    explanation = "Vectorize a safe Series.apply arithmetic lambda."

    def match(self, node: cst.CSTNode) -> bool:
        if not isinstance(node, cst.Call) or not _call_attr(node, "apply") or _axis_one(node):
            return False
        lam = _lambda(node)
        return bool(lam and _receiver_safe(node.func.value) and (p := _param(lam)) and _safe_expr(lam.body, p, allow_bare=True))

    def rewrite(self, node: cst.CSTNode) -> Optional[cst.CSTNode]:
        if not self.match(node) or not isinstance(node, cst.Call):
            return None
        lam = _lambda(node)
        assert lam is not None
        return _replace(lam.body, _param(lam) or "", node.func.value)


class RowApplyRule(Rule):
    id = "AP001"
    title = PATTERN_MESSAGES[id]
    explanation = "Vectorize a safe row-wise DataFrame.apply arithmetic lambda."

    def match(self, node: cst.CSTNode) -> bool:
        if not isinstance(node, cst.Call) or not _call_attr(node, "apply") or not _axis_one(node):
            return False
        lam = _lambda(node)
        return bool(lam and _receiver_safe(node.func.value) and (p := _param(lam)) and _safe_expr(lam.body, p, allow_bare=False))

    def rewrite(self, node: cst.CSTNode) -> Optional[cst.CSTNode]:
        if not self.match(node) or not isinstance(node, cst.Call):
            return None
        lam = _lambda(node)
        assert lam is not None
        return _replace(lam.body, _param(lam) or "", node.func.value)


def _growth(node: cst.For) -> Optional[Tuple[str, str, cst.Call, cst.BaseExpression]]:
    if not isinstance(node.body, cst.IndentedBlock) or len(node.body.body) != 1:
        return None
    stmt = node.body.body[0]
    if not isinstance(stmt, cst.SimpleStatementLine) or len(stmt.body) != 1 or not isinstance(stmt.body[0], cst.Assign):
        return None
    assign = stmt.body[0]
    if len(assign.targets) != 1 or not isinstance(assign.targets[0].target, cst.Name) or not isinstance(assign.value, cst.Call):
        return None
    target = assign.targets[0].target.value
    call = assign.value
    if not isinstance(call.func, cst.Attribute):
        return None
    if isinstance(call.func.value, cst.Name) and call.func.value.value == "pd" and call.func.attr.value == "concat":
        if len(call.args) < 1 or not isinstance(call.args[0].value, cst.List) or len(call.args[0].value.elements) != 2:
            return None
        values = [e.value for e in call.args[0].value.elements if isinstance(e, cst.Element)]
        if len(values) != 2 or not isinstance(values[0], cst.Name) or values[0].value != target:
            return None
        return "AP004", target, call, values[1]
    if isinstance(call.func.value, cst.Name) and call.func.value.value == "np" and call.func.attr.value == "append":
        if any(a.keyword and a.keyword.value == "axis" for a in call.args) or not call.args or not isinstance(call.args[0].value, cst.Name) or call.args[0].value.value != target:
            return None
        if len(call.args) != 2:
            return None
        return "AP005", target, call, call.args[1].value
    return None


class _GrowthRule(Rule):
    def __init__(self, pattern: str):
        self.id = pattern
        self.title = PATTERN_MESSAGES[pattern]
        self.explanation = "Collect loop pieces and concatenate once."

    def match(self, node: cst.CSTNode) -> bool:
        return isinstance(node, cst.For) and (_growth(node) or ())[0:1] == (self.id,)

    def rewrite(self, node: cst.CSTNode) -> Optional[cst.CSTNode]:
        if not isinstance(node, cst.For):
            return None
        found = _growth(node)
        if not found or found[0] != self.id:
            return None
        _, target, call, piece = found
        name = f"_fastframe_{target}_parts"
        if self.id == "AP004":
            options = ", " + ", ".join(cst.Module([]).code_for_node(a) for a in call.args[1:]) if len(call.args) > 1 else ""
            suffix = f"pd.concat({name}{options})"
            piece_code = cst.Module([]).code_for_node(piece)
        else:
            suffix = f"np.concatenate({name})"
            piece_code = f"np.atleast_1d({cst.Module([]).code_for_node(piece)})"
        append = cst.parse_statement(f"{name}.append({piece_code})\n")
        loop = node.with_changes(body=cst.IndentedBlock(body=(append,)))
        return cst.FlattenSentinel((cst.parse_statement(f"{name} = [{target}]\n"), loop, cst.parse_statement(f"{target} = {suffix}\n")))


class ConcatRule(_GrowthRule):
    def __init__(self) -> None:
        super().__init__("AP004")


class NpAppendRule(_GrowthRule):
    def __init__(self) -> None:
        super().__init__("AP005")


class IterrowsRule(Rule):
    id = "AP003"
    title = PATTERN_MESSAGES[id]
    explanation = "Replace a safe iterrows arithmetic append with a vectorized extend."

    def match(self, node: cst.CSTNode) -> bool:
        return self._parts(node) is not None

    def _parts(self, node: cst.CSTNode):
        if not isinstance(node, cst.For) or not isinstance(node.iter, cst.Call) or not _call_attr(node.iter, "iterrows"):
            return None
        if not isinstance(node.target, cst.Tuple) or len(node.target.elements) != 2 or not isinstance(node.target.elements[0].value, cst.Name) or not isinstance(node.target.elements[1].value, cst.Name):
            return None
        index, row = node.target.elements[0].value.value, node.target.elements[1].value.value
        if index != "_" or not isinstance(node.body, cst.IndentedBlock) or len(node.body.body) != 1:
            return None
        stmt = node.body.body[0]
        if not isinstance(stmt, cst.SimpleStatementLine) or len(stmt.body) != 1 or not isinstance(stmt.body[0], cst.Expr):
            return None
        expr = stmt.body[0].value
        if not isinstance(expr, cst.Call) or not _call_attr(expr, "append") or len(expr.args) != 1:
            return None
        value = expr.args[0].value
        if not _safe_expr(value, row, allow_bare=False):
            return None
        return row, node.iter.func.value, expr.func.value, value

    def rewrite(self, node: cst.CSTNode) -> Optional[cst.CSTNode]:
        parts = self._parts(node)
        if parts is None:
            return None
        row, frame, output, value = parts
        vector = _replace(value, row, frame)
        code = cst.Module([]).code_for_node(vector)
        return cst.parse_statement(f"{cst.Module([]).code_for_node(output)}.extend(({code}).tolist())\n")


class DowncastRule(Rule):
    id = "AP006"
    title = PATTERN_MESSAGES[id]
    explanation = "Review dtype downcast manually."

    def match(self, node: cst.CSTNode) -> bool:
        return isinstance(node, cst.Call) and bool(_call_attr(node, "astype")) and _downcast_dtype(node)


RULES: Sequence[Rule] = (RowApplyRule(), ApplyRule(), IterrowsRule(), ConcatRule(), NpAppendRule(), DowncastRule())


class _Detector(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self) -> None:
        self.findings: List[Tuple[cst.CSTNode, Rule, object]] = []

    def _visit(self, node: cst.CSTNode) -> None:
        for rule in RULES:
            if rule.match(node):
                self.findings.append((node, rule, self.get_metadata(PositionProvider, node)))
                break

    def visit_Call(self, node: cst.Call) -> None:
        self._visit(node)

    def visit_For(self, node: cst.For) -> None:
        self._visit(node)


def detect(source: str) -> List[Finding]:
    module = cst.parse_module(source)
    detector = _Detector()
    wrapper = MetadataWrapper(module)
    wrapper.visit(detector)
    result = []
    for node, rule, pos in detector.findings:
        result.append(Finding(rule.id, pos.start.line, pos.start.column, rule.title, _downcast_saving(node) if rule.id == "AP006" else None, rule.id == "AP006"))
    return result


class _Rewriter(cst.CSTTransformer):
    def __init__(self, pattern: Optional[str] = None, occurrence: Optional[int] = None) -> None:
        self.pattern = pattern
        self.occurrence = occurrence
        self._matched = 0

    def _rewrite(self, node: cst.CSTNode) -> Optional[cst.CSTNode]:
        for rule in RULES:
            if self.pattern is not None and rule.id != self.pattern:
                continue
            if not rule.match(node):
                continue
            if self.occurrence is not None:
                self._matched += 1
                if self._matched != self.occurrence:
                    continue
            replacement = rule.rewrite(node)
            if replacement is not None:
                return replacement
        return None

    def leave_Call(self, original: cst.Call, updated: cst.Call) -> cst.BaseExpression:
        return self._rewrite(original) or updated  # type: ignore[return-value]

    def leave_For(self, original: cst.For, updated: cst.For) -> cst.BaseStatement:
        return self._rewrite(original) or updated  # type: ignore[return-value]


def rewrite(source: str, pattern: Optional[str] = None, occurrence: Optional[int] = None) -> str:
    """Rewrite all rules, or one rule occurrence when requested."""
    if occurrence is not None and occurrence < 1:
        raise ValueError("occurrence must be at least 1")
    return cst.parse_module(source).visit(_Rewriter(pattern, occurrence)).code


rewrite_source = rewrite
detect_antipatterns = detect
