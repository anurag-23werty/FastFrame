"""Focused AP001 benchmark: 100k row-wise arithmetic applications."""

import numpy as np
import pandas as pd

rng = np.random.default_rng(1001)
df = pd.DataFrame({"a": rng.integers(1, 100, 100_000), "b": rng.integers(1, 100, 100_000)})
result = df.apply(lambda row: row["a"] + row["b"], axis=1)
