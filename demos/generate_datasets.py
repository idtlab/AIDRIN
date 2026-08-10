#!/usr/bin/env python3
"""Generate synthetic datasets for AIDRIN metric demos.

Creates 3 CSV files in the same directory as this script:
  - messy_sensor_data.csv   (data quality demo)
  - loan_applications.csv   (feature analysis + fairness demo)
  - patient_records.csv      (privacy metrics demo)

Usage:
    python generate_datasets.py
"""

import os

import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RNG = np.random.default_rng(42)


def generate_messy_sensor_data(n: int = 500) -> pd.DataFrame:
    """Sensor data with missing values, duplicates, and outliers."""
    locations = ["building_A", "building_B", "building_C", "rooftop", "basement"]
    statuses = ["active", "idle", "error", "maintenance"]

    df = pd.DataFrame(
        {
            "sensor_id": [f"S{i:04d}" for i in range(n)],
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h"),
            "temperature": RNG.normal(22.0, 3.0, n),
            "humidity": RNG.normal(55.0, 10.0, n),
            "pressure": RNG.normal(1013.0, 5.0, n),
            "status": RNG.choice(statuses, n, p=[0.7, 0.15, 0.1, 0.05]),
            "location": RNG.choice(locations, n),
        }
    )

    # Inject outliers (~3% extreme values)
    outlier_idx = RNG.choice(n, size=15, replace=False)
    df.loc[outlier_idx[:8], "temperature"] = RNG.uniform(55, 80, 8)
    df.loc[outlier_idx[8:], "pressure"] = RNG.uniform(950, 960, 7)

    # Inject missing values (~15% of rows)
    for col in ["temperature", "humidity", "pressure", "status"]:
        mask = RNG.random(n) < 0.15
        df.loc[mask, col] = np.nan

    # Inject duplicate rows (~5%)
    dup_idx = RNG.choice(n, size=25, replace=False)
    dups = df.iloc[dup_idx].copy()
    df = pd.concat([df, dups], ignore_index=True)

    return df


def generate_loan_applications(n: int = 2000) -> pd.DataFrame:
    """Loan data with class imbalance and sensitive attributes for fairness."""
    genders = ["Male", "Female", "Non-binary"]
    ethnicities = ["White", "Black", "Hispanic", "Asian", "Other"]
    educations = ["High School", "Bachelor", "Master", "PhD", "Other"]
    purposes = ["home", "auto", "education", "business", "personal"]

    age = RNG.integers(21, 65, n)
    income = np.clip(RNG.lognormal(10.8, 0.6, n), 20000, 300000).astype(int)
    credit_score = np.clip(RNG.normal(680, 80, n), 300, 850).astype(int)
    employment_years = np.clip(RNG.exponential(6, n), 0, 40).round(1)
    education = RNG.choice(educations, n, p=[0.30, 0.35, 0.20, 0.10, 0.05])
    gender = RNG.choice(genders, n, p=[0.48, 0.48, 0.04])
    ethnicity = RNG.choice(ethnicities, n, p=[0.55, 0.15, 0.15, 0.10, 0.05])
    loan_amount = np.clip(RNG.lognormal(10, 0.8, n), 1000, 500000).astype(int)
    loan_purpose = RNG.choice(purposes, n)

    # Approval model: correlated with income + credit_score, with demographic disparity
    score = (
        0.4 * (credit_score - 300) / 550
        + 0.3 * (income - 20000) / 280000
        + 0.15 * (employment_years / 40)
        + 0.05 * np.array([{"PhD": 1, "Master": 0.8, "Bachelor": 0.6}.get(e, 0.3) for e in education])
        + RNG.normal(0, 0.1, n)
    )
    # Introduce demographic disparity (lower threshold for some groups)
    ethnicity_adj = np.array([
        -0.05 if e in ("Black", "Hispanic") else 0.0 for e in ethnicity
    ])
    score += ethnicity_adj

    # ~75% approval rate
    threshold = np.percentile(score, 25)
    approved = (score >= threshold).astype(int)

    df = pd.DataFrame(
        {
            "applicant_id": [f"A{i:05d}" for i in range(n)],
            "age": age,
            "income": income,
            "credit_score": credit_score,
            "employment_years": employment_years,
            "education": education,
            "gender": gender,
            "ethnicity": ethnicity,
            "loan_amount": loan_amount,
            "loan_purpose": loan_purpose,
            "approved": approved,
        }
    )
    return df


def generate_patient_records(n: int = 1000) -> pd.DataFrame:
    """Healthcare data with quasi-identifiers for privacy metrics."""
    diagnoses = [
        "Hypertension", "Diabetes", "Asthma", "Depression",
        "Arthritis", "COPD", "Heart Failure", "Migraine",
    ]
    medications = [
        "Lisinopril", "Metformin", "Albuterol", "Sertraline",
        "Ibuprofen", "Tiotropium", "Furosemide", "Sumatriptan",
    ]
    genders = ["Male", "Female"]
    marital = ["Single", "Married", "Divorced", "Widowed"]

    # Use limited zip codes to create small equivalence classes
    zip_codes = [f"{z:05d}" for z in RNG.choice(
        [10001, 10002, 10003, 20001, 20002, 30301, 30302, 60601, 60602, 90210],
        n,
    )]

    age = np.clip(RNG.normal(55, 15, n), 18, 95).astype(int)
    gender = RNG.choice(genders, n, p=[0.48, 0.52])
    marital_status = RNG.choice(marital, n, p=[0.25, 0.45, 0.20, 0.10])
    diagnosis = RNG.choice(diagnoses, n)
    medication = RNG.choice(medications, n)
    bp_systolic = np.clip(RNG.normal(130, 20, n), 90, 200).astype(int)
    cholesterol = np.clip(RNG.normal(200, 40, n), 100, 350).astype(int)
    readmitted = RNG.choice([0, 1], n, p=[0.75, 0.25])

    df = pd.DataFrame(
        {
            "patient_id": [f"P{i:05d}" for i in range(n)],
            "age": age,
            "zip_code": zip_codes,
            "gender": gender,
            "marital_status": marital_status,
            "diagnosis": diagnosis,
            "medication": medication,
            "blood_pressure_systolic": bp_systolic,
            "cholesterol": cholesterol,
            "readmitted": readmitted,
        }
    )
    return df


def main():
    datasets = [
        ("messy_sensor_data.csv", generate_messy_sensor_data),
        ("loan_applications.csv", generate_loan_applications),
        ("patient_records.csv", generate_patient_records),
    ]

    for filename, generator in datasets:
        path = os.path.join(SCRIPT_DIR, filename)
        df = generator()
        df.to_csv(path, index=False)
        print(f"  {filename}: {df.shape[0]} rows x {df.shape[1]} cols -> {path}")

    print("Done.")


if __name__ == "__main__":
    main()
