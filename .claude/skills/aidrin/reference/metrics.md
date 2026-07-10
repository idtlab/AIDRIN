# AIDRIN metrics reference (CLI)

## Contents

- [Invocation & conventions](#invocation--conventions)
- [Data quality](#data-quality): completeness, duplicity, outliers
- [Impact on AI](#impact-on-ai): correlations, feature_relevance
- [Fairness & bias](#fairness--bias): class_imbalance, statistical_rates, representation_rate
- [Data governance](#data-governance): k_anonymity, l_diversity, t_closeness, entropy_risk, single_attribute_risk, multiple_attribute_risk
- [Privacy](#privacy): differential_privacy (currently unavailable)
- [Batch config format](#batch-config-format)

---

## Invocation & conventions

- `aidrin run <metric> <file> <args...>` — args are POSITIONAL, in the order
  shown by `aidrin run <metric> -h`. NOT `--flags`.
- Metric names use **dash form** under `aidrin run` (`class-imbalance`,
  `feature-relevance`, `k-anonymity`, etc.). Underscore forms are NOT accepted by
  `aidrin run`.
- Column lists are comma-separated strings; quote them: `"col_a,col_b"`.
- `--detail` defaults on for `run`/`batch` (full JSON). Visualizations are
  stripped by default.
- Examples use bare `aidrin`. If `aidrin` is not on PATH, see
  reference/installation.md for the invocation form (e.g. `uv run aidrin`).
- Per metric below: **Syntax**, **Args (in order)**, **Output keys**,
  **Direction** (what higher/lower means; no fixed pass/fail threshold).

---

## Data quality

### completeness

- **Syntax:** `aidrin run completeness <file>`
- **Args:** none (file only)
- **Output keys:**
  - `Completeness scores` — object mapping each column name to its completeness ratio (0–1)
  - `Overall Completeness` — scalar, mean completeness across all columns
- **Direction:** higher overall completeness = fewer missing values = better.

**Example:**

```bash
aidrin run completeness examples/sample_data/csv/adult.csv
```

---

### duplicity

- **Syntax:** `aidrin run duplicity <file>`
- **Args:** none (file only)
- **Output keys:**
  - `Duplicity scores` — object with key `"Overall duplicity of the dataset"` → scalar ratio (0–1)
- **Direction:** higher duplicate ratio = more redundancy = worse. 0.0 = no duplicates.

**Example:**

```bash
aidrin run duplicity examples/sample_data/csv/adult.csv
```

---

### outliers

- **Syntax:** `aidrin run outliers <file>`
- **Args:** none (file only)
- **Output keys:**
  - `Outlier scores` — object mapping each numerical column name to its outlier proportion, plus `"Overall outlier score"` as an aggregate scalar
- **Direction:** higher outlier proportion = more anomalies to inspect. 0.0 = no outliers detected in that column.

**Example:**

```bash
aidrin run outliers examples/sample_data/csv/adult.csv
```

---

## Impact on AI

### correlations

- **Syntax:** `aidrin run correlations <file> "<columns>"`
- **Args (in order):**
  1. `columns` — comma-separated list of columns to correlate
- **Output keys:**
  - `Correlations Analysis Categorical` — object of categorical correlation results (empty if no categorical columns selected)
  - `Correlations Analysis Numerical` — object with `Description` and `Method` ("Spearman") for numerical pairs
  - `Correlation Scores` — object mapping `"colA vs colB"` pairs to Spearman coefficients (−1 to 1)
- **Direction:** |value| → 1 = stronger association between columns; values near 0 = weak/no association.

**Example:**

```bash
aidrin run correlations examples/sample_data/csv/adult.csv "age,education.num"
```

---

### feature_relevance

- **Syntax:** `aidrin run feature-relevance <file> [categorical-columns] [numerical-columns] <target-column>`
- **Args (in order):**
  1. `categorical-columns` — comma-separated categorical columns (optional; omit by skipping to numerical or target)
  2. `numerical-columns` — comma-separated numerical columns (optional; provide at least one of categorical or numerical)
  3. `target-column` — the column whose values the features are evaluated against
- **Notes:** At least one of `categorical-columns` or `numerical-columns` is required; providing neither exits with error 2. Positional order matters — the last positional is always `target-column`.
- **Output keys:**
  - `Pearson Correlation to Target` — object mapping each feature (with categorical columns one-hot expanded) to its Pearson correlation coefficient against the target
  - `Description` — string explaining the method (minimal cleaning, one-hot encode categoricals, label-encode target, Pearson coefficient)
- **Direction:** higher |value| = feature more informative about the target. Positive values = same direction as target; negative = inverse.

**Example (both categorical and numerical columns provided):**

```bash
aidrin run feature-relevance examples/sample_data/csv/adult.csv \
  "workclass,education,occupation" "age,education.num" income
```

---

## Fairness & bias

### class_imbalance

- **Syntax:** `aidrin run class-imbalance <file> <target-column>`
- **Args (in order):**
  1. `target-column` — column whose class distribution is measured
- **Output keys:**
  - `Imbalance degree` — object with:
    - `Imbalance Degree score` — scalar (0 = perfectly balanced; higher = more skewed)
    - `Description` — string explaining the ID ratio relative to uniform and worst-case distributions
- **Direction:** higher imbalance degree = more skewed classes = worse for training.

**Example:**

```bash
aidrin run class-imbalance examples/sample_data/csv/adult.csv income
```

---

### statistical_rates

- **Syntax:** `aidrin run statistical-rates <file> <y-true-column> <sensitive-attribute-column>`
- **Args (in order):**
  1. `y-true-column` — ground-truth label column (the class/outcome column)
  2. `sensitive-attribute-column` — column defining the sensitive groups (e.g. sex, race)
- **Output keys:**
  - `Statistical Rates` — object mapping each sensitive group value to a nested object of class → proportion within that group
  - `TSD scores` — object mapping each class label to a Total Statistical Disparity scalar
  - `Description` — string clarifying this is label-distribution per group, not model-output fairness
- **Direction:** LABEL-DISTRIBUTION metric — reports the proportion of each class within each sensitive group. Large gaps in class proportions across groups = representation skew to flag. This metric operates on raw dataset labels, not model predictions.

**Example:**

```bash
aidrin run statistical-rates examples/sample_data/csv/adult.csv income sex
```

---

### representation_rate

- **Syntax:** `aidrin run representation-rate <file> "<columns>"`
- **Args (in order):**
  1. `columns` — comma-separated categorical columns to assess for representation
- **Output keys:**
  - `Probability ratios` — object mapping `"Column: '<col>', Probability ratio for '<valA>' to '<valB>'"` → scalar ratio; each pair is most-frequent vs. less-frequent category values
  - `Description` — string explaining that higher values imply overrepresentation relative to another group
- **Direction:** ratios far from 1.0 indicate over/under-representation of categories relative to each other.

**Example:**

```bash
aidrin run representation-rate examples/sample_data/csv/adult.csv "sex,race"
```

---

## Data governance

### k_anonymity

- **Syntax:** `aidrin run k-anonymity <file> "<quasi-identifiers>"`
- **Args (in order):**
  1. `quasi-identifiers` — comma-separated columns that together could re-identify individuals
- **Output keys:**
  - `k-Value` — integer; minimum group size sharing the same quasi-identifier values
  - `Description` — string; higher k values are preferred (stronger anonymity); k = 1 means unique rows exist = high risk
- **Direction:** higher k = less re-identifiable. k = 1 = unique rows = high risk.

**Example:**

```bash
aidrin run k-anonymity examples/sample_data/csv/adult.csv "age,sex,race"
```

---

### l_diversity

- **Syntax:** `aidrin run l-diversity <file> "<quasi-identifiers>" <sensitive-column>`
- **Args (in order):**
  1. `quasi-identifiers` — comma-separated quasi-identifier columns
  2. `sensitive-column` — the single sensitive attribute column
- **Output keys:**
  - `l-Value` — integer; minimum number of distinct sensitive values within any equivalence class
  - `Description` — string; higher l values preferred (less risk of attribute disclosure)
- **Direction:** higher l = more diverse sensitive values per QI group = lower disclosure risk.

**Example:**

```bash
aidrin run l-diversity examples/sample_data/csv/adult.csv "age,sex,race" income
```

---

### t_closeness

- **Syntax:** `aidrin run t-closeness <file> "<quasi-identifiers>" <sensitive-column>`
- **Args (in order):**
  1. `quasi-identifiers` — comma-separated quasi-identifier columns
  2. `sensitive-column` — the single sensitive attribute column
- **Output keys:**
  - `t-Value` — float (0–1); maximum Earth Mover's Distance between a group's sensitive distribution and the overall distribution
  - `Description` — string; lower t values preferred (distribution closer to overall = less information leakage)
- **Direction:** lower t = group distribution closer to overall = lower risk. Values near 1 indicate a group whose sensitive distribution diverges significantly.

**Example:**

```bash
aidrin run t-closeness examples/sample_data/csv/adult.csv "age,sex,race" income
```

---

### entropy_risk

- **Syntax:** `aidrin run entropy-risk <file> "<quasi-identifiers>"`
- **Args (in order):**
  1. `quasi-identifiers` — comma-separated quasi-identifier columns
- **Output keys:**
  - `Entropy-Value` — float; uncertainty in identifying individuals within equivalence classes
  - `Description` — string; higher entropy preferred (greater anonymity, lower re-identification risk)
- **Direction:** higher entropy = more uncertainty in identifying individuals = lower re-identification risk. Values near 0 indicate low uncertainty (high risk).

**Example:**

```bash
aidrin run entropy-risk examples/sample_data/csv/adult.csv "age,sex,race"
```

---

### single_attribute_risk

- **Syntax:** `aidrin run single-attribute-risk <file> <id-column> "<eval-columns>"`
- **Args (in order):**
  1. `id-column` — the column serving as a unique row identifier
  2. `eval-columns` — comma-separated columns to evaluate independently for Markov-model risk
- **Output keys:**
  - `Descriptive statistics of the risk scores` — object mapping each eval column to a nested stats object with keys: `mean`, `std`, `min`, `25%`, `50%`, `75%`, `max`
  - `Description` — string; lower values preferred; high-risk features may require anonymization
- **Direction:** higher risk score = more re-identifiable via that individual attribute. Scores near 1.0 indicate the attribute is nearly unique per row.

**Example:**

```bash
aidrin run single-attribute-risk examples/sample_data/csv/adult.csv ID "age,occupation"
```

(Replace `ID` with your dataset's row-identifier column.)

---

### multiple_attribute_risk

- **Syntax:** `aidrin run multiple-attribute-risk <file> <id-column> "<eval-columns>"`
- **Args (in order):**
  1. `id-column` — the column serving as a unique row identifier
  2. `eval-columns` — comma-separated columns to evaluate jointly for Markov-model risk
- **Output keys:**
  - `Description` — string; lower values preferred; evaluates joint risk of the column combination
  - `Descriptive statistics of the risk scores` — object with aggregate stats keys: `mean`, `std`, `min`, `25%`, `50%`, `75%`, `max`
  - `Dataset Risk Score` — scalar summarizing overall re-identification risk for the evaluated column set
- **Direction:** higher risk score = the combination of those attributes more easily re-identifies individuals. Scores near 1.0 indicate high joint risk.

**Example:**

```bash
aidrin run multiple-attribute-risk examples/sample_data/csv/adult.csv ID "age,occupation"
```

(Replace `ID` with your dataset's row-identifier column.)

---

## Privacy

### differential_privacy

- **Syntax:** `aidrin run differential-privacy <file> "<columns>" <epsilon>`
- **Args (in order):**
  1. `columns` — comma-separated numerical columns to protect with Laplacian noise
  2. `epsilon` — privacy budget scalar (smaller = stronger privacy guarantee, more noise; typical range 0.1–10.0)
- **Output keys:**
  - `Mean of feature <col>(before noise)` — scalar
  - `Variance of feature <col>(before noise)` — scalar
  - `Mean of feature <col>(after noise)` — scalar
  - `Variance of feature <col>(after noise)` — scalar
  - `Description` — string explaining the Laplacian noise mechanism
  - `Noisy file saved` — confirmation string
- **Direction:** lower epsilon = more privacy (more noise added). Compare before/after variance to quantify the noise impact per column.

**Example:**

```bash
aidrin run differential-privacy examples/sample_data/csv/adult.csv "age,hours.per.week" 1.0
```

---

## Batch config format

`aidrin batch <config.json|.yaml>`. The config is FLAT/global — one set of
column keys is applied to every metric listed in `metrics`. Use batch only for
metrics that share identical args (e.g. the zero-arg quality baseline).

Config keys use dash names (underscore forms are also accepted in batch config). Set `"save-images": false` to suppress the PNG writes that `aidrin run` produces by default:

| Key                          | Used by metric(s)                              |
|------------------------------|------------------------------------------------|
| `file_path`                  | all                                            |
| `metrics`                    | all (list of metric names)                     |
| `target-column`              | class_imbalance, feature_relevance             |
| `quasi-identifiers`          | k_anonymity, l_diversity, t_closeness, entropy_risk |
| `sensitive-column`           | l_diversity, t_closeness                       |
| `sensitive-attribute-column` | statistical_rates                              |
| `y-true-column`              | statistical_rates                              |
| `categorical-columns`        | feature_relevance                              |
| `numerical-columns`          | feature_relevance                              |
| `id-column`                  | single_attribute_risk, multiple_attribute_risk |
| `eval-columns`               | single_attribute_risk, multiple_attribute_risk |
| `columns`                    | correlations, representation_rate              |
| `epsilon`                    | differential_privacy                           |
| `save-images`                | any metric that produces visualizations        |

**Example — zero-arg quality baseline (all three share no required column args):**

```json
{"file_path": "data.csv", "metrics": ["completeness", "duplicity", "outliers"]}
```

**Example — governance baseline (shared quasi-identifiers + sensitive-column):**

```json
{
  "file_path": "data.csv",
  "metrics": ["k_anonymity", "l_diversity", "t_closeness", "entropy_risk"],
  "quasi-identifiers": "age,sex,race",
  "sensitive-column": "income"
}
```

Note: `entropy_risk` ignores `sensitive-column` (it takes only `quasi-identifiers`);
the extra key is silently ignored by batch.
