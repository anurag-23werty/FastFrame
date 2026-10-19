"""Focused AP003 benchmark: 100k iterrows arithmetic appends."""

import numpy as np
import pandas as pd

rng = np.random.default_rng(1003)
df = pd.DataFrame({"a": rng.integers(1, 100, 100_000), "b": rng.integers(1, 100, 100_000)})
result = []
for _, row in df.iterrows():
    result.append(row["a"] + row["b"])
