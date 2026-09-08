"""Metric definitions for readiness report PDF footnotes."""

READINESS_METRIC_GLOSSARY = {
    "feature_profile": (
        "A per-column snapshot of whether each feature is usable for modeling. "
        "Combines missingness, cardinality, and value balance into a readiness status."
    ),
    "feature_type_codes": (
        "Feature type abbreviations in the profile table: "
        "N = Numerical, C = Categorical, D = Datetime, B = Boolean."
    ),
    "pct_missing": (
        "Share of rows where this feature is missing (null/NaN). "
        "High missingness reduces reliability and may require imputation or dropping the column."
    ),
    "n_unique": (
        "Number of distinct non-missing values. Very low values suggest constants; "
        "very high values relative to row count may indicate IDs or free text."
    ),
    "pct_dominant": (
        "Share of rows taken by the most frequent value (the mode). "
        "Values near 100% mean the column is almost constant."
    ),
    "profile_status": (
        "Readiness verdict for this feature. Poor: high missingness, constant, or ID-like. "
        "Warning: moderate issues. Good: no major issues detected."
    ),
    "overall_dq_grade": (
        "Average of the data-quality KPIs (completeness, uniqueness, outlier-cleanliness). "
        "Higher is better."
    ),
    "analysis_scope": (
        "This section evaluates every column automatically; no features or targets are chosen by the user."
    ),
    "completeness": (
        "Overall share of non-missing values across all features."
    ),
    "uniqueness": (
        "One minus the proportion of duplicate rows. Low uniqueness means many exact duplicate records."
    ),
    "outlier_cleanliness": (
        "One minus the mean outlier proportion across numerical features (IQR method)."
    ),
    "features_analyzed": (
        "Number of columns included in the automated correlation scan after pruning."
    ),
    "leakage_risk_pairs": (
        "Feature pairs with correlation |score| ≥ 0.95 — nearly duplicate or derived from each other."
    ),
    "redundant_pairs": (
        "Feature pairs with correlation |score| between 0.8 and 0.95 — likely redundant."
    ),
    "isolated_features": (
        "Features whose strongest correlation to any other feature is below 0.1."
    ),
    "most_related_pairs": (
        "The feature pairs with the highest absolute correlation scores from the automated scan."
    ),
    "overall_impact_grade": (
        "Average of impact KPIs (leakage safety, redundancy, informativeness). Higher is better."
    ),
    "leakage_safety": (
        "Whether any feature pairs exceed the leakage-risk correlation threshold (|score| ≥ 0.95)."
    ),
    "redundancy": (
        "Derived from the count of highly correlated redundant pairs (|score| ≥ 0.8)."
    ),
    "informativeness": (
        "Share of analyzed features that have at least one meaningful correlation to another feature."
    ),
    "overall_fairness_grade": (
        "Average of fairness KPIs (representation balance, label balance, outcome parity). Higher is better."
    ),
    "representation_balance": (
        "1 divided by the worst group probability ratio across auto-selected sensitive attributes."
    ),
    "label_balance": (
        "Derived from the Imbalance Degree of the auto-selected target column."
    ),
    "outcome_parity": (
        "1 minus the maximum TSD (standard deviation of class rates across sensitive groups)."
    ),
    "representation_imbalance": (
        "Sensitive attributes where the largest group probability ratio exceeds the threshold."
    ),
    "minority_classes": (
        "Target classes that make up less than 5% of rows."
    ),
    "outcome_disparities": (
        "Target classes whose outcome rates vary most across sensitive groups (high TSD)."
    ),
    "cdd_disparities": (
        "Sensitive groups flagged by Conditional Demographic Disparity."
    ),
    "overall_governance_grade": (
        "Average of governance KPIs (anonymity, diversity, distribution leakage, linkage risk, PHI exposure)."
    ),
    "anonymity_k": (
        "Minimum equivalence-class size (k) on auto-selected quasi-identifiers."
    ),
    "diversity_l": (
        "Minimum l-diversity on the auto-selected sensitive attribute within QI groups."
    ),
    "distribution_t": (
        "Maximum t-closeness (TVD) between group and global sensitive-attribute distributions."
    ),
    "single_linkage_risk": (
        "Worst mean Marketer/Prosecutor re-identification risk across single quasi-identifiers."
    ),
    "linkage_risk": (
        "Mean MM re-identification risk when all auto-selected quasi-identifiers are combined."
    ),
    "phi_exposure": (
        "HIPAA-style pattern scan on auto-selected text columns. Not a regulatory certification."
    ),
    "low_anonymity": (
        "Privacy metrics (e.g. k-Anonymity) below warning thresholds."
    ),
    "hipaa_phi": (
        "Columns where HIPAA-like identifier patterns were detected during the automated scan."
    ),
    "high_linkage_risk": (
        "Quasi-identifiers or QI combinations with high Marketer/Prosecutor re-identification risk."
    ),
    "attribute_disclosure": (
        "l-Diversity or t-Closeness signals suggesting sensitive-attribute values may be inferable."
    ),
    "fair_compliance": (
        "Optional metadata assessment (DCAT or Datacite JSON); not derived from the dataset file."
    ),
}

FOOTNOTE_LABELS = {
    "feature_profile": "Per-feature readiness profile",
    "feature_type_codes": "Feature type codes",
    "pct_missing": "% missing",
    "n_unique": "# unique",
    "pct_dominant": "% dominant",
    "profile_status": "Status",
    "overall_dq_grade": "Overall data quality grade",
    "analysis_scope": "Analysis scope",
    "completeness": "Completeness",
    "uniqueness": "Uniqueness",
    "outlier_cleanliness": "Outlier cleanliness",
    "features_analyzed": "Features analyzed",
    "leakage_risk_pairs": "Leakage risk pairs",
    "redundant_pairs": "Redundant pairs",
    "isolated_features": "Isolated features",
    "most_related_pairs": "Most related pairs",
    "overall_impact_grade": "Overall impact grade",
    "leakage_safety": "Leakage safety",
    "redundancy": "Redundancy",
    "informativeness": "Informativeness",
    "overall_fairness_grade": "Overall fairness grade",
    "representation_balance": "Representation balance",
    "label_balance": "Label balance",
    "outcome_parity": "Outcome parity",
    "representation_imbalance": "Representation imbalance",
    "minority_classes": "Minority classes",
    "outcome_disparities": "Outcome disparities",
    "cdd_disparities": "CDD disparities",
    "overall_governance_grade": "Overall governance grade",
    "anonymity_k": "Anonymity (k)",
    "diversity_l": "Diversity (l)",
    "distribution_t": "Distribution (t)",
    "single_linkage_risk": "Single linkage risk",
    "linkage_risk": "Linkage risk",
    "phi_exposure": "PHI exposure",
    "low_anonymity": "Low anonymity",
    "hipaa_phi": "HIPAA PHI",
    "high_linkage_risk": "High linkage risk",
    "attribute_disclosure": "Attribute disclosure",
    "fair_compliance": "FAIR compliance",
}

_FEATURE_TYPE_ABBR = {
    "numerical": "N",
    "categorical": "C",
    "datetime": "D",
    "boolean": "B",
}

_STATUS_LABELS = {
    "good": "Good",
    "warning": "Warning",
    "poor": "Poor",
}
