"""Focused AP004 benchmark: concatenate approximately 500 chunks."""

import numpy as np
import pandas as pd

rng = np.random.default_rng(1004)
chunks = [pd.DataFrame({"value": rng.integers(1, 100, 200)}) for _ in range(500)]
result = chunks[0].iloc[:0]
for chunk in chunks:
    result = pd.concat([result, chunk], ignore_index=True)
