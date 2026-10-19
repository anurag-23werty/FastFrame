import numpy as np
import pandas as pd


df = pd.DataFrame(
    {
        "units": [2, 4, 6, 8],
        "price": [10.0, 12.5, 9.0, 11.0],
        "region": ["east", "west", "east", "west"],
    }
)

row_totals = df.apply(lambda row: row["units"] * row["price"], axis=1)
scaled_units = df["units"].apply(lambda value: value * 2)

values = []
for _, row in df.iterrows():
    values.append(row["units"] * row["price"])

combined = df.iloc[:0]
for chunk in [df.iloc[:2], df.iloc[2:]]:
    combined = pd.concat([combined, chunk], ignore_index=True)

amounts = np.array([], dtype=float)
for value in [10.0, 20.0, 30.0, 40.0]:
    amounts = np.append(amounts, value)

wide_units = df["units"].astype("int64")
