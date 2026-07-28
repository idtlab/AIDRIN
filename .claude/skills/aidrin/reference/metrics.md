# AIDRIN metrics reference (CLI)

## Contents

- [Invocation & conventions](#invocation--conventions)
- [Data quality](#data-quality): completeness, duplicity, outliers, row-level-completeness, duplicity-by-features, feature-coverage-ratio, temporal-completeness, null-count-trend, file-reference-validation
- [Data structure](#data-structure): constant-feature-count, max-pairwise-correlation, skewness, kurtosis
- [Impact on AI](#impact-on-ai): correlations, feature-relevance
- [Fairness & bias](#fairness--bias): class-imbalance, statistical-rates, representation-rate
- [Data governance](#data-governance): k-anonymity, l-diversity, t-closeness, entropy-risk, single-attribute-risk, multiple-attribute-risk, hipaa-compliance
- [Privacy](#privacy): differential-privacy (currently unavailable)
- [Batch config format](#batch-config-format)

---

## Invocation & conventions

- `aidrin run <metric> <file> <args...>` — args are POSITIONAL, in the order
  shown by `aidrin run <metric> -h`. NOT `--flags`.
- Metric names use **dash form** under `aidrin run` (`class-imbalance`,
  `feature-relevance`, `k-anonymity`, etc.). Underscore forms are NOT accepted by
  `aidrin run`.
- Exception: the completeness-family metrics (`row-level-completeness`,
  `feature-coverage-ratio`, `temporal-completeness`, `null-count-trend`) take
  their arguments as NAMED `--flags` (e.g. `--required-columns`, `--frequency`),
  not positionally.
- `file-reference-validation` takes its target list positionally and its path and
  result controls as named flags.
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
  - `Overall Completeness` — scalar, **column-wise**: the mean of the per-column
    non-missing rates (`1 - df.isnull().mean().mean()`). (Previously this was a
    row-wise score — the fraction of rows with no missing cell; see `CHANGELOG.md`.)
- **Direction:** higher overall completeness = fewer missing values = better.
- **Web display name:** in the web Data Quality panel this metric is labeled
  **"Column-Level Completeness"** (the metric id / CLI command is still `completeness`).

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

### row-level-completeness

- **Syntax:** `aidrin run row-level-completeness <file> --required-columns "<cols>"`
- **Args:**
  - `--required-columns` (required) — comma-separated columns that must ALL be non-null for a row to count as complete
- **Output keys:**
  - `Row-Level Completeness (%)` — scalar percentage (0–100) of rows whose required columns are all non-null
  - `Complete rows` — integer count of fully-complete rows
  - `Total rows` — integer total row count
  - `Description` — string
- **Direction:** higher = more rows have every required field populated = better.

**Example:**

```bash
aidrin run row-level-completeness examples/sample_data/csv/adult.csv --required-columns "age,workclass"
```

---

### duplicity-by-features

- **Syntax:** `aidrin run duplicity-by-features <file> --duplicate-columns "<cols>"`
- **Args:**
  - `--duplicate-columns` (required) — comma-separated columns to compare when detecting duplicate rows
- **Output keys:**
  - `Duplicate count` — integer count of duplicate rows (rows after the first occurrence of each value combination)
  - `Duplicate percentage` — scalar percentage (0–100) of rows that are duplicates
  - `Total rows` — integer total row count
  - `Duplicate groups` — list of `{"Feature values": {...}, "Row count": int}`, the top 10 largest duplicate groups, sorted descending by size
  - `Description` — string
- **Direction:** lower duplicate percentage = fewer redundant rows = better.

**Example:**

```bash
aidrin run duplicity-by-features examples/sample_data/csv/adult.csv --duplicate-columns "age,workclass"
```

---

### feature-coverage-ratio

- **Syntax:** `aidrin run feature-coverage-ratio <file> --threshold <0–1>`
- **Args:**
  - `--threshold` (float 0–1, default `0.9`) — a feature is "covered" when its non-null rate ≥ threshold
- **Output keys:**
  - `Feature Coverage Ratio (%)` — scalar percentage of features whose non-null rate meets/exceeds the threshold
  - `Threshold` — the threshold used
  - `Covered features` — integer count of covered features
  - `Total features` — integer column count
  - `Feature Coverage Ratio Visualization` — base64-encoded PNG bar chart
  - `Description` — string
- **Direction:** higher = more features clear the coverage bar = better.

**Example:**

```bash
aidrin run feature-coverage-ratio examples/sample_data/csv/adult.csv --threshold 0.9
```

---

### temporal-completeness

- **Syntax:** `aidrin run temporal-completeness <file> --timestamp-column <col> --frequency <freq>`
- **Args:**
  - `--timestamp-column` (required) — the datetime column to evaluate
  - `--frequency` — expected interval frequency, one of `ms, s, min, h, D, W, ME, QE, YE` (default `D`)
- **Output keys:**
  - `Temporal Completeness (%)` — scalar percentage of expected intervals present between the earliest and latest timestamps
  - `Frequency` — the frequency used
  - `Expected intervals` — integer count of intervals expected across the range
  - `Present intervals` — integer count of intervals actually present
  - `Range start` / `Range end` — earliest / latest timestamp
  - `Temporal Completeness Visualization` — base64-encoded PNG timeline chart
  - `Description` — string
- **Direction:** higher = fewer gaps in the time series = better.

**Example:**

```bash
aidrin run temporal-completeness path/to/timeseries.csv --timestamp-column time --frequency D
```

---

### null-count-trend

- **Syntax:** `aidrin run null-count-trend <file> --batch-column <col> [--target-columns "<cols>"]`
- **Args:**
  - `--batch-column` (required) — column that groups rows into batches
  - `--target-columns` (optional) — comma-separated columns to count nulls in; defaults to all other columns
- **Output keys:**
  - `Null counts by batch` — object mapping each batch value to its total null-cell count across the target columns
  - `Batch column` — the batch column used
  - `Target columns` — the columns whose nulls were counted
  - `Null Count Trend Visualization` — base64-encoded PNG chart
  - `Description` — string
- **Direction:** batches with spiking null counts flag quality regressions; flat/low counts = stable quality.

**Example:**

```bash
aidrin run null-count-trend path/to/batches.csv --batch-column machine_id --target-columns "temperature,pressure"
```

---

### file-reference-validation

- **Syntax:** `aidrin run file-reference-validation <file> "<targets>" [--target-match exact|regex] [--base-dir <dir>] [--max-results <n>] [--scan-limit <n>]`
- **Args:**
  - `<targets>` (required) — comma-separated path-bearing columns, or string-valued HDF5 dataset paths
  - `--target-match` — interpret targets as exact names (default) or regular expressions matched against complete target names
  - `--base-dir` — directory used to resolve relative references; defaults to the manifest file's directory
  - `--max-results` — cap for invalid-reference and file-metadata detail arrays (default `100`; `0` means unlimited)
  - `--scan-limit` — optional global cap on values scanned (`0` or omitted means unlimited)
- **Output keys:**
  - `Summary` — scanned and unscanned counts, valid/invalid/missing counts, uniqueness counts, validity rate, completion status, and detail truncation flags
  - `Target summaries` — the same core counts per selected target
  - `Invalid references` — occurrence-level location, value, resolved path, reason, and message
  - `File metadata` — one record per resolved regular file, including size, owner when available, creation time when the OS exposes one, and modification time
  - `Errors` — target-level errors, such as selecting a numeric target
- **Direction:** a complete scan with `all_references_valid: true` means every scanned occurrence is a non-missing reference to a regular file. Inspect `scan_complete` and truncation flags before drawing conclusions.
- **Host semantics:** paths are resolved and checked on the machine running AIDRIN. The MCP tool checks the MCP server host.

**Example:**

```bash
aidrin run file-reference-validation path/to/manifest.csv "path,image_path" --base-dir /data/project
aidrin run file-reference-validation path/to/manifest.csv '.*_path' --target-match regex --base-dir /data/project
```

---

## Data structure

These four take **no arguments** (like the zero-arg quality baseline).
`max-pairwise-correlation`, `skewness`, and `kurtosis` operate on the numeric,
non-constant columns.

### constant-feature-count

- **Syntax:** `aidrin run constant-feature-count <file>`
- **Args:** none (file only)
- **Output keys:**
  - `Constant feature count` — integer count of columns with exactly one distinct value (null counts as a value: an all-null column is constant; a column with one real value plus nulls is not, since that's two distinct values)
  - `Total features` — integer total column count
  - `Constant features` — object mapping each constant column name to its single value (`null` for an all-null column)
- **Direction:** any constant features present = columns carrying no information for modeling and candidates for removal.

**Example:**

```bash
aidrin run constant-feature-count examples/sample_data/csv/adult.csv
```

---

### max-pairwise-correlation

- **Syntax:** `aidrin run max-pairwise-correlation <file>`
- **Args (in order):** none
- **Output keys:**
  - `Max Pairwise Correlation` — scalar, strongest absolute Pearson correlation between any two numeric features (0–1)
  - `Most Correlated Pair` — string `"colA ~ colB"`
  - `Top Correlated Pairs` — list of `{"pair", "correlation"}` objects, ranked
  - `Numeric Features Considered` — integer count of numeric non-constant columns used
  - `Max Pairwise Correlation Visualization` — base64 heatmap (stripped by default)
  - `Description` — string
- **Direction:** near 1.0 = redundant/collinear features (consider dropping one); near 0 = independent.

**Example:**

```bash
aidrin run max-pairwise-correlation examples/sample_data/csv/adult.csv
```

---

### skewness

- **Syntax:** `aidrin run skewness <file>`
- **Args (in order):** none
- **Output keys:**
  - `Skewness` — object mapping each numeric feature to its skewness
  - `Most Skewed Feature` — string
  - `Max Absolute Skewness` — scalar
  - `Numeric Features Considered` — integer
  - `Skewness Visualization` — base64 bar chart (stripped by default)
  - `Description` — string
- **Direction:** |value| far from 0 = asymmetric/long-tailed distribution; ~0 = symmetric.

**Example:**

```bash
aidrin run skewness examples/sample_data/csv/adult.csv
```

---

### kurtosis

- **Syntax:** `aidrin run kurtosis <file>`
- **Args (in order):** none
- **Output keys:**
  - `Kurtosis` — object mapping each numeric feature to its excess kurtosis (Fisher; normal = 0)
  - `Most Extreme Kurtosis Feature` — string
  - `Max Absolute Excess Kurtosis` — scalar
  - `Numeric Features Considered` — integer
  - `Kurtosis Visualization` — base64 bar chart (stripped by default)
  - `Description` — string
- **Direction:** positive = heavier tails / more outliers than normal; negative = lighter tails.

**Example:**

```bash
aidrin run kurtosis examples/sample_data/csv/adult.csv
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

### feature-relevance

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

### class-imbalance

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

### statistical-rates

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

### representation-rate

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

### k-anonymity

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

### l-diversity

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

### t-closeness

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

### entropy-risk

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

### single-attribute-risk

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

### multiple-attribute-risk

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

### hipaa-compliance

- **Syntax:** `aidrin run hipaa-compliance <file> "<columns>"`
- **Args (in order):**
  1. `columns` — comma-separated columns to scan for HIPAA-regulated PHI patterns
- **Output keys:** one entry per column where at least one match was found (columns with no matches are omitted; no matches anywhere returns `{}`):
  - `<column_name>.total_flags` — int; count of matched values in that column
  - `<column_name>.potential_types_detected` — array; identifier types found, e.g. `US_SSN`, `EMAIL_ADDRESS`, `PHONE_OR_FAX`, `IP_ADDRESS`, `URL`, `VIN_NUMBER`, `MEDICAL_IDS`, `VALID_POSTAL_CODE`
  - `<column_name>.examples` — array; up to 5 example matched values
- **Direction:** any flags present = potential HIPAA-regulated PHI in that column; an empty `{}` result means none of the scanned columns matched. Postal codes are validated against a real geocode database (pgeocode, US by default) rather than a bare 5-digit regex, to cut down false positives.

**Example:**

```bash
aidrin run hipaa-compliance examples/sample_data/csv/adult.csv "native.country,fnlwgt"
```

Note: this is regex/pattern-based PHI detection (SSN, email, phone, IP, URL, VIN, medical IDs, postal codes) — not a full HIPAA Safe Harbor 18-identifier audit. Treat findings as leads to review, not a compliance certification.

---

## Privacy

### differential-privacy

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

Config keys use dash names. Set `"save-images": false` to suppress the PNG writes that `aidrin run` produces by default:

| Key                          | Used by metric(s)                              |
|------------------------------|------------------------------------------------|
| `file_path`                  | all                                            |
| `metrics`                    | all (list of metric names)                     |
| `target-column`              | class-imbalance, feature-relevance             |
| `quasi-identifiers`          | k-anonymity, l-diversity, t-closeness, entropy-risk |
| `sensitive-column`           | l-diversity, t-closeness                       |
| `sensitive-attribute-column` | statistical-rates                              |
| `y-true-column`              | statistical-rates                              |
| `categorical-columns`        | feature-relevance                              |
| `numerical-columns`          | feature-relevance                              |
| `id-column`                  | single-attribute-risk, multiple-attribute-risk |
| `eval-columns`               | single-attribute-risk, multiple-attribute-risk |
| `columns`                    | correlations, representation-rate              |
| `epsilon`                    | differential-privacy                           |
| `required-columns`           | row-level-completeness                         |
| `threshold`                  | feature-coverage-ratio                         |
| `timestamp-column`           | temporal-completeness                          |
| `frequency`                  | temporal-completeness                          |
| `batch-column`               | null-count-trend                               |
| `target-columns`             | null-count-trend                               |
| `save-images`                | any metric that produces visualizations        |

**Example — zero-arg quality baseline (all three share no required column args):**

```json
{"file_path": "data.csv", "metrics": ["completeness", "duplicity", "outliers"]}
```

**Example — governance baseline (shared quasi-identifiers + sensitive-column):**

```json
{
  "file_path": "data.csv",
  "metrics": ["k-anonymity", "l-diversity", "t-closeness", "entropy-risk"],
  "quasi-identifiers": "age,sex,race",
  "sensitive-column": "income"
}
```

Note: `entropy-risk` ignores `sensitive-column` (it takes only `quasi-identifiers`);
the extra key is silently ignored by batch.
