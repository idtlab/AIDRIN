from __future__ import annotations

import pandas as pd
from pathlib import Path


def load_dataset() -> pd.DataFrame:
    """Load the UCI Individual Household Electric Power Consumption dataset."""
    data_path = Path(__file__).resolve().parents[1] / "use_cases" / "power_consumption" / "data" / "household_power_consumption.txt"
    return pd.read_csv(data_path, sep=";", low_memory=False)
