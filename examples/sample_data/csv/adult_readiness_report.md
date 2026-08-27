# Dataset AI-Readiness Report: adult.csv

## 1. Dataset overview
- Path / format: `examples/sample_data/csv/adult.csv` (CSV)
- Rows / columns: 32,561 rows × 16 columns
- Schema (from AIDRIN's parser):
  - Numerical (7): `ID`, `age`, `fnlwgt`, `education.num`, `capital.gain`, `capital.loss`, `hours.per.week`
  - Categorical (9): `workclass`, `education`, `marital.status`, `occupation`, `relationship`, `race`, `sex`, `native.country`, `income`

## 2. Intended use
Train a supervised model to classify individuals' income level (income classification task).

## 3. Confirmed column roles
> Privacy and fairness results below are conditional on these role assignments.
- Target column: `income` (`<=50K` / `>50K`)
- Sensitive attribute(s): `sex`, `race`
- Quasi-identifiers: not evaluated — governance/privacy metrics were out of scope for this training-focused assessment (dataset is not being published/shared)
- ID column: `ID`
- No role corrections were requested by the user.

## 4. Findings by dimension

### Data quality
- **Completeness**: 1.0 overall (100%) — every column reports zero nulls.
  - ⚠️ **Caveat**: the classic Adult dataset encodes missing values as the literal string `"?"`, not NaN. AIDRIN's completeness check does not catch this. A direct check found: `workclass` 5.64% (1,836 rows), `occupation` 5.66% (1,843 rows), `native.country` 1.79% (583 rows) are `"?"` placeholders — effectively missing data the reported 100% completeness score does not reflect.
- **Duplicity**: 0.0 — no duplicate rows detected.
- **Outliers**: overall outlier score 0.0498. Per-column: `hours.per.week` 27.66% (highest by far), `education.num` 3.68%, `fnlwgt` 3.05%, `age` 0.44%, `capital.gain`/`capital.loss` 0.0%. `hours.per.week`'s outlier rate is notably high — likely reflects legitimate part-time/overtime spread rather than data errors, worth a visual check.

### Data structure
- **Constant features**: 0 of 16 columns are constant — no dead columns to drop.
- **Max pairwise correlation** (numerical): 0.36 between `ID` ~ `capital.loss` (an artifact of `ID` being a row index correlating with anything ordered; not a real relationship — `ID` should be excluded from modeling). Next highest is `ID` ~ `capital.gain` (0.22), then `education.num` ~ `hours.per.week` (0.15). No concerning collinearity among genuine features.
- **Skewness**: `capital.gain` is extremely skewed (11.95), `capital.loss` skewed (4.59), `fnlwgt` moderately skewed (1.45). Others near-symmetric.
- **Kurtosis**: `capital.gain` has extreme excess kurtosis (154.8) and `capital.loss` (20.4) — both heavy-tailed, consistent with most values being 0 and a few very large. Expected for these two columns; consider binning/log-transform before modeling.

### Impact on AI
- **Feature relevance to `income`** (Pearson, one-hot categoricals): strongest signals are `marital.status_Married-civ-spouse` (0.44), `relationship_Husband` (0.40), `marital.status_Never-married` (−0.32), `education.num` (0.34), `relationship_Own-child` (−0.23), `sex_Male`/`sex_Female` (±0.22), `age` (0.23), `hours.per.week` (0.23), `capital.gain` (0.22), `occupation_Exec-managerial` (0.21). `fnlwgt` is essentially irrelevant (−0.01), as expected (it's a census sampling weight, not a demographic feature).
- **Correlations** (categorical + numerical, Spearman/Cramér-style): strongest inter-feature associations are `marital.status` ↔ `relationship` (0.57), `relationship` ↔ `marital.status` (0.49), `sex` ↔ `relationship` (0.43), `workclass` ↔ `occupation` (0.29). These reflect real redundancy — `marital.status`, `relationship`, and `sex` partly encode overlapping information (e.g. "Husband"/"Wife" implies both marital status and sex), worth considering during feature engineering to avoid double-counting the same signal.

### Fairness & bias
- **Class imbalance** (target `income`): Imbalance Degree score 0.5184 (moderate-to-high skew; dataset is ~76% `<=50K` / ~24% `>50K` per the schema stats). Plan to use class weighting, resampling, or an appropriate metric (F1/AUC, not raw accuracy) when training.
- **Statistical rates by `sex`** (label distribution, not model output): Female → `>50K` in 10.95% of cases; Male → `>50K` in 30.57% of cases. TSD score 0.098 — a substantial gap in the raw labels across sex.
- **Statistical rates by `race`**: `>50K` rates range from 8.9% (Other) to 26.6% (Asian-Pac-Islander) and 25.6% (White), down to 12.4% (Black) and 11.6% (Amer-Indian-Eskimo). TSD score 0.074.
- **Representation rate**: `sex` Male:Female ratio 2.02:1. `race` White dominates heavily — White:Black 8.9:1, White:Asian-Pac-Islander 26.8:1, White:Amer-Indian-Eskimo 89.4:1, White:Other 102.6:1.
- **Interpretation**: these are pre-existing label/representation patterns in the raw data (historical income disparities and under-representation of non-White groups), not evidence of model bias yet — but training on this data as-is will likely propagate both patterns into any classifier unless deliberately mitigated.

### Data governance
Not run — out of scope for a training-only use case per the confirmed plan. Reconsider if this dataset will later be published or shared externally (k-anonymity, l-diversity, t-closeness, entropy-risk, single/multiple-attribute-risk would apply then, using `age`, `sex`, `race`, `native.country`, etc. as quasi-identifiers).

### Privacy
Not run — same scope note as governance above. `hipaa-compliance` was also not run; this dataset is census/employment data, not health data, so it's a low-priority check here.

## 5. Domain-grounded findings
- **Question**: "Does the model comply with income reporting standards described in the literature?"
- **Answer / finding**: The pipeline generated and executed code confirming `income` has no missing values, two clean categories (`<=50K`, `>50K`), and all required columns are present. It found no explicit "income reporting standard" in the indexed literature; instead it surfaced general ML fairness/transparency principles (FAT/ML workshop, GDPR profiling-transparency requirements) and recommended: (1) keep the `income` column clearly/consistently labeled, (2) verify the two income categories align with any actual regulatory income-reporting thresholds relevant to the intended use, (3) document the income-categorization methodology for stakeholders.
- **Complexity / confidence**: `moderate` query class, overall score 0.62 (profile 0.50, domain 0.75, code 0.50). Domain knowledge was flagged as the primary knowledge source.
- **Suggested remediation**: standardize income category documentation and align with GDPR/FAT-ML-style transparency practices (see recommended actions above).
- **Source**: `examples/agentic/power_consumption/sources/` (16 PDFs indexed, 1,175 chunks). Top-retrieved passage came from `1711.02368v1.pdf`, a paper on ML interpretability/GDPR profiling transparency.
- ⚠️ **Important caveat**: this literature set is about **electric-load forecasting, smart grids, and voltage control** — it contains no actual income-reporting, census, or fair-lending standards. The one relevant-sounding passage (GDPR/FAT-ML transparency) was a coincidental tangential match, not a real income-reporting standard. **Treat this domain-grounded answer as a demonstration of the pipeline mechanics only, not a real compliance finding.** For a genuine answer, point the pipeline at literature such as fair lending regulations (ECOA/Regulation B), census income-reporting documentation, or algorithmic fairness standards specific to credit/income decisions.

## 6. Risks & flags
- **Completeness is overstated**: `"?"` placeholders in `workclass`, `occupation`, `native.country` are not counted as missing (see Data quality above). Recommend re-running completeness after mapping `"?"` → NaN, or explicitly imputing/dropping those rows before training.
- **`ID` correlating with `capital.gain`/`capital.loss`**: an artifact of row ordering, not a real signal — must exclude `ID` from features.
- **Class imbalance** (0.52) plus **strong group skew** in the `>50K` label by both `sex` (Male 3× Female rate) and `race` (White/Asian-Pac-Islander ~2× Black/Amer-Indian-Eskimo/Other rate) — training naively risks a model that under-predicts high income for women and several racial minority groups, and under-represents those same groups in raw counts (Male:Female 2:1, White:Other 103:1).
- **`capital.gain`/`capital.loss` are extremely skewed/heavy-tailed** — most values are 0 with rare large spikes; consider log-transform or binning.
- **Redundant categorical features**: `marital.status`, `relationship`, and `sex` are moderately-to-strongly correlated with each other (up to 0.57) — some information overlap to be aware of in feature selection.

## 7. Suggested next steps
- Decide how to treat `"?"` placeholder values (impute, drop, or encode as an explicit "Unknown" category) before training.
- Exclude `ID` from the feature set.
- Consider fairness mitigation (reweighing, threshold adjustment, or fairness-constrained training) given the sex/race disparities in the label distribution, especially if this model will inform real income-related decisions.
- Re-point the domain-grounded pipeline at literature actually relevant to income reporting / fair lending (e.g. ECOA/Reg B, census documentation) if a genuine domain-compliance check is needed.
- The readiness decision (proceed to training as-is vs. remediate first) is yours to make based on the findings above.

## 8. Appendix
- Raw metric outputs (saved locally, not in the repo):
  `/private/tmp/claude-502/-Users-hiniduma-1-Documents-AIDRIN-copy-AIDRIN/587e9663-d36d-4464-a9e7-e591938f383b/scratchpad/adult_assessment/`
  - `completeness.json`, `duplicity.json`, `outliers.json`
  - `constant_feature_count.json`, `max_pairwise_correlation.json`, `skewness.json`, `kurtosis.json`
  - `feature_relevance.json`, `correlations.json`
  - `class_imbalance.json`, `statistical_rates_sex.json`, `statistical_rates_race.json`, `representation_rate.json`
  - `metadata.txt`, `config.yaml`, `agentic_results.json` (domain-grounded pipeline)
- Calls/commands executed:
  - `aidrin run completeness examples/sample_data/csv/adult.csv`
  - `aidrin run duplicity examples/sample_data/csv/adult.csv`
  - `aidrin run outliers examples/sample_data/csv/adult.csv`
  - `aidrin run constant-feature-count examples/sample_data/csv/adult.csv`
  - `aidrin run max-pairwise-correlation examples/sample_data/csv/adult.csv`
  - `aidrin run skewness examples/sample_data/csv/adult.csv`
  - `aidrin run kurtosis examples/sample_data/csv/adult.csv`
  - `aidrin run feature-relevance examples/sample_data/csv/adult.csv "workclass,education,marital.status,occupation,relationship,race,sex,native.country" "age,fnlwgt,education.num,capital.gain,capital.loss,hours.per.week" income`
  - `aidrin run correlations examples/sample_data/csv/adult.csv "age,fnlwgt,education.num,capital.gain,capital.loss,hours.per.week,workclass,education,marital.status,occupation,relationship,race,sex,native.country"`
  - `aidrin run class-imbalance examples/sample_data/csv/adult.csv income`
  - `aidrin run statistical-rates examples/sample_data/csv/adult.csv income sex`
  - `aidrin run statistical-rates examples/sample_data/csv/adult.csv income race`
  - `aidrin run representation-rate examples/sample_data/csv/adult.csv "sex,race"`
  - `aidrin agentic build-index -c config.yaml`
  - `aidrin agentic run -c config.yaml -o agentic_results.json`
- Remedied dataset: none applied yet — see remediation offer below.
