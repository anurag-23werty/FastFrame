"""Deterministic 200k-row sales workload covering all FastFrame rules."""

import numpy as np
import pandas as pd

rng = np.random.default_rng(2026)
row_count = 200_000
df = pd.DataFrame(
    {
        "units": rng.integers(1, 25, size=row_count),
        "price": rng.uniform(5.0, 250.0, size=row_count).round(2),
        "region": rng.choice(["east", "west", "north", "south"], size=row_count),
    }
)
work = df.iloc[:20_000]

row_totals = work.apply(lambda row: row["units"] * row["price"], axis=1)
scaled_units = work["units"].apply(lambda value: value * 2)

values = []
for _, row in work.iterrows():
    values.append(row["units"] * row["price"])

combined = work.iloc[:0]
for chunk in np.array_split(work, 20):
    combined = pd.concat([combined, chunk], ignore_index=True)

amounts = np.array([], dtype=float)
for value in work["price"].to_numpy()[:2_000]:
    amounts = np.append(amounts, value)

wide_units = work["units"].astype("int64")
