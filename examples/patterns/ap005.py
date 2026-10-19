"""Focused AP005 benchmark: approximately 20k NumPy appends."""

import numpy as np

rng = np.random.default_rng(1005)
values = rng.integers(1, 100, 20_000)
result = np.array([], dtype=np.int64)
for value in values:
    result = np.append(result, value)
