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

row_totals = df.apply(lambda row: row["units"] * row["price"], axis=1)
scaled_units = df["units"].apply(lambda value: value * 2)

values = []
for _, row in df.iterrows():
    values.append(row["units"] * row["price"])

combined = df.iloc[:0]
chunks = np.array_split(df, 20)
for chunk in chunks:
    combined = pd.concat([combined, chunk], ignore_index=True)

amounts = np.array([], dtype=float)
for value in df["price"].to_numpy()[:2_000]:
    amounts = np.append(amounts, value)

wide_units = df["units"].astype("int64")
