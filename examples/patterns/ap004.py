"""Focused AP004 benchmark: concatenate 2,000 prebuilt 500-row chunks."""

import numpy as np
import pandas as pd

rng = np.random.default_rng(1004)
chunks = [pd.DataFrame({"value": rng.integers(1, 100, 500)}) for _ in range(2_000)]
result = pd.DataFrame({"value": []})
for chunk in chunks:
    result = pd.concat([result, chunk], ignore_index=True)
