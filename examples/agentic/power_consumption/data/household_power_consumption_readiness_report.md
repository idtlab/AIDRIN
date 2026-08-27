# Dataset AI-Readiness Report: household_power_consumption (UCI Individual Household Electric Power Consumption)

## 1. Dataset overview
- Path / format: `examples/agentic/power_consumption/data/household_power_consumption.txt` — semicolon-delimited `.txt`, not a format AIDRIN's own parser reads directly. Converted (via the same logic as `loader.py`: `pd.read_csv(sep=";", na_values=["?"])`) to a plain-comma CSV so AIDRIN's summarizer and CLI metrics could parse it; the converted copy was a scratch working file only, not committed to the repo.
- Rows / columns: 2,075,259 rows × 9 columns
- Schema (from AIDRIN's parser):
  - `Date` : categorical (1442 unique, dd/mm/yyyy)
  - `Time` : categorical (1440 unique, hh:mm:ss — minute-level)
  - `Global_active_power`, `Global_reactive_power`, `Voltage`, `Global_intensity`, `Sub_metering_1`, `Sub_metering_2`, `Sub_metering_3` : numerical (float)

## 2. Intended use
General quality / AI-readiness check — no specific downstream model or publication use stated yet.

## 3. Confirmed column roles
> Privacy and fairness results below are conditional on these role assignments.
- Target column: none (no fairness/privacy/supervised-training metrics were requested or run)
- Sensitive attribute(s): none
- Quasi-identifiers: none
- ID column: none
[Scope was intentionally limited to data quality and data structure — no governance, privacy, or fairness metrics were run.]

## 4. Findings by dimension

### Data quality
| Metric | Result | Meaning |
|---|---|---|
| Completeness (overall) | **0.9903** | Column-wise mean non-missing rate. `Date`/`Time` are 100% complete; all 7 numerical sensor columns are each 98.75% complete (missing ≈1.25% of rows — matches the documented gap, e.g. April 28, 2007). Higher = better; this is a minor, well-understood gap. |
| Duplicity | **0.0** | No duplicate rows at all. Good — no redundant-row cleanup needed. |
| Outliers (overall) | **0.0254** | Average outlier proportion across numerical columns. Per-column: `Global_intensity` 4.93%, `Global_active_power` 4.63%, `Sub_metering_2` 3.76%, `Voltage` 2.49%, `Global_reactive_power` 1.97%, `Sub_metering_1`/`Sub_metering_3` 0.0%. None exceed 5%, but the sub-metering columns' heavy skew (see below) means "outlier" here likely reflects real high-usage events (appliances switching on), not data errors. |

### Data structure
| Metric | Result | Meaning |
|---|---|---|
| Constant-feature-count | **0 / 9** | No dead/constant columns — every feature carries information. |
| Max pairwise correlation | **0.9989** between `Global_active_power` ~ `Global_intensity` | Near-perfect collinearity — these two are almost redundant (power ≈ voltage × intensity, so this is physically expected). For most modeling uses, keep one or engineer a combined feature rather than feeding both as independent predictors. |
| Skewness | Most skewed: `Sub_metering_2` (**7.09**); also high for `Sub_metering_1` (5.94), `Global_intensity` (1.85), `Global_active_power` (1.79), `Global_reactive_power` (1.26); `Voltage` near-symmetric (−0.33) | Sub-metering columns are heavily right-skewed — consistent with "mostly idle, occasional appliance spikes." Consider log/Box-Cox transforms if a model assumes normality. |
| Kurtosis | Most extreme: `Sub_metering_2` (**57.91** excess kurtosis); `Sub_metering_1` also high (35.64); `Global_active_power`/`Global_intensity` moderately heavy-tailed (~4.2–4.6); `Sub_metering_3` slightly light-tailed (−1.28); `Voltage` near-normal (0.72) | Very heavy tails on the sub-metering columns reinforce the skewness finding — rare but large spikes dominate the distribution. |

### Impact on AI (correlations, Spearman, all 7 numerical columns)
- `Global_active_power` ~ `Global_intensity`: **0.995** (near-perfect — expected physically, see collinearity above)
- `Global_active_power` ~ `Sub_metering_3` (water heater/AC): **0.604**; ~ `Sub_metering_1` (kitchen): **0.335**; ~ `Sub_metering_2` (laundry): **0.186**
- `Voltage` correlates weakly negatively with everything else (−0.09 to −0.35) — largely independent signal.
- `Global_reactive_power` is only weakly related to the sub-metering columns (0.07–0.43).
- Not run: feature-relevance / class-imbalance (no target column was specified — out of scope for this general-quality pass).

### Fairness & bias
Not run — no sensitive attribute or target was in scope for this assessment (single-household sensor data; no obvious grouping variable).

### Data governance / Privacy
Not run — not requested (scope was general quality/structure, not publish/PII).

## 5. Domain-grounded findings
- Sources indexed: 16 PDFs in `examples/agentic/power_consumption/sources/` (load-forecasting, smart-meter, and privacy/fairness-in-ML literature), 1175 chunks, `text-embedding-ada-002`.
- Model: `gpt-5.2` (used for retrieval answering, code execution/self-healing, complexity scoring, and remediation — as configured in the repo's existing `config.yaml`).

**Q1: Which EU regulation is cited as requiring that the consequences of profiling be informed to the data subject?**
- Answer: **GDPR (General Data Protection Regulation)**
- Complexity/confidence: class `moderate` (overall score 0.49); primary knowledge source = domain literature (domain_score 0.95, profile_score 0.0) — this is a literature-lookup question, not something derivable from the dataset itself.
- Suggested remediation: no data gap found; recommended action is documentation-only — record the cited regulation (GDPR) and its source excerpt in the dataset's compliance/data-dictionary notes for auditability. Priority: low.
- Source: `1711.02368v1.pdf`

**Q2: Is more than 80% of the data resampled to align with widely-adopted smart-meter industry standards (to reduce behavioral noise)?**
- Answer: **False**
- Complexity/confidence: class `moderate` (overall score 0.59); primary knowledge source = both profile and domain (domain_score 0.75, profile_score 0.35, code_score 0.5) — the literature supplied the operational threshold (15-minute sampling is the cited industry standard), and code computed the actual alignment against it using the dataset's minute-level `Date`/`Time` columns.
- Suggested remediation (priority: high): resample the series to a strict 15-minute grid (with explicit aggregation and gap handling) and validate that ≥80% (ideally 100%) of the resulting timestamps land on 15-minute boundaries before using the data for forecasting benchmarks that assume this standard.
- Source: `1907.09207v1.pdf` (15-minute smart-meter sampling standard, 96 timesteps/day), with `fdata-05-972206.pdf` as supporting context.

## 6. Risks & flags
- **Near-total collinearity** (0.9989) between `Global_active_power` and `Global_intensity` — feeding both as independent model inputs risks multicollinearity issues (unstable coefficients in linear models); not an issue for tree-based/ensemble methods.
- **Extreme skew/kurtosis in `Sub_metering_1`/`Sub_metering_2`** — heavy-tailed appliance-level readings could dominate loss functions unless transformed or the model is robust to outliers.
- **Native sampling is 1-minute, not the 15-minute smart-meter standard** the domain literature cites — flagged above (Q2) as a gap if this dataset is meant to be benchmarked against or compared with data resampled to that standard.
- 1.25% missingness in the 7 sensor columns is low but non-random by date (documented gap around April 28, 2007) — worth checking whether missingness clusters elsewhere in time before imputing.

## 7. Suggested next steps
[Non-prescriptive — the readiness decision is yours.]
- If training a supervised/forecasting model: decide on a target (e.g. `Global_active_power`) and re-run `feature-relevance` / `correlations` against it; consider dropping or combining `Global_intensity` with `Global_active_power` given the near-perfect collinearity.
- If comparing against smart-meter literature benchmarks: resample to 15-minute intervals as suggested by the domain-grounded finding (Q2), and consider running `temporal-completeness` (needs a single combined `Date`+`Time` timestamp column) to quantify gaps at the target frequency.
- If planning to publish or share: this assessment did not touch privacy/governance metrics — that would need a follow-up pass with agreed quasi-identifiers before any release decision.
- Consider a log/Box-Cox transform on `Sub_metering_1`/`Sub_metering_2` if using models sensitive to skew.

## 8. Appendix
- Raw metric outputs: `examples/agentic/power_consumption/data/aidrin_raw/` — `data_quality.json`, `constant_feature_count.json`, `correlations.json`, `max_pairwise_correlation.json`, `skewness.json`, `kurtosis.json`, `agentic_results.json` (full domain-grounded pipeline output: profile + queries + token usage).
- Calls/commands executed:
  - `aidrin list`, `aidrin remote list` (preflight)
  - `python3 -c "pd.read_csv(..., sep=';', na_values=['?']).to_csv(...)"` (format conversion, scratch-only)
  - `aidrin summarize household_power_consumption.csv --summary`
  - `aidrin data-quality household_power_consumption.csv --detail`
  - `aidrin run constant-feature-count household_power_consumption.csv`
  - `aidrin run correlations household_power_consumption.csv "Global_active_power,Global_reactive_power,Voltage,Global_intensity,Sub_metering_1,Sub_metering_2,Sub_metering_3"`
  - `aidrin run max-pairwise-correlation household_power_consumption.csv`
  - `aidrin run skewness household_power_consumption.csv`
  - `aidrin run kurtosis household_power_consumption.csv`
  - `aidrin agentic build-index -c examples/agentic/power_consumption/config.yaml`
  - `aidrin agentic run -c examples/agentic/power_consumption/config.yaml -o agentic_results.json`
- Remedied dataset: none — no remediation applied yet (see below).
