"""
Data loader for the UCI Individual Household Electric Power Consumption dataset.

Dataset: https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption

Place `household_power_consumption.txt` (extracted from the downloaded zip) in the
`data/` directory next to this file before running.
"""

from __future__ import annotations

import pandas as pd
from pathlib import Path


def load_dataset() -> pd.DataFrame:
    data_path = Path(__file__).parent / "data" / "household_power_consumption.txt"
    if not data_path.exists():
        raise FileNotFoundError(
            f"Dataset not found at {data_path}.\n"
            "Download it from: https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption\n"
            "and place household_power_consumption.txt in the data/ directory."
        )
    return pd.read_csv(data_path, sep=";", low_memory=False, na_values=["?"])
