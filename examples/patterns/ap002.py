"""Focused AP002 benchmark: 100k arithmetic Series applications."""

import numpy as np
import pandas as pd

rng = np.random.default_rng(1002)
df = pd.DataFrame({"a": rng.integers(1, 100, 100_000)})
result = df["a"].apply(lambda value: value * 2)
