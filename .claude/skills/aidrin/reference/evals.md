# End-to-end eval results — aidrin skill

Evaluated against `examples/sample_data/` on 2026-06-23. CLI invocation: `uv run aidrin`.

---

## Scenario 1: Training intent — zero-arg baseline + training metrics (CSV)

**Commands:**
```bash
# Batch config: {"file_path":"examples/sample_data/csv/adult.csv","metrics":["completeness","duplicity","outliers"]}
uv run aidrin batch /tmp/dq.json
uv run aidrin run class-imbalance examples/sample_data/csv/adult.csv income
uv run aidrin run feature-relevance examples/sample_data/csv/adult.csv workclass,occupation age,capital.gain income
```

**Outcome:** All three commands exited 0 and returned valid JSON.
- `completeness`: all 16 columns score 1.0 (no missing values).
- `duplicity`: 0.0 (no duplicates).
- `outliers`: `hours.per.week` highest at 0.2766; overall 0.0498.
- `class-imbalance`: Imbalance Degree 0.5184 (moderately skewed toward `<=50K`).
- `feature-relevance`: Pearson correlations returned for one-hot expanded categoricals and numerical columns.

**PASS** — building blocks for training intent work end-to-end on CSV.

---

## Scenario 2: Non-CSV schema read (JSON file — highest-risk path)

**Commands:**
```python
from aidrin.file_handling.file_parser import read_file
df = read_file(("examples/sample_data/json/adult.json", "adult.json", ".json"))
print(df.columns.tolist())  # -> ['ID', 'age', 'workclass', ..., 'income']
print(df.shape)              # -> (32561, 16)
```
```bash
uv run aidrin run class-imbalance examples/sample_data/json/adult.json income
```

**Outcome:** `read_file` returned the same 16 columns as the CSV (no reshape surprises for this dataset). `aidrin run` on the JSON file exited 0 and returned identical JSON output to the CSV run (Imbalance Degree 0.5184).

**PASS** — non-CSV schema read and metric execution work correctly; SKILL.md Step 3 advice to use `read_file` is sound.

---

## Scenario 3: Absent metric → scaffold custom metric end-to-end

User requests `data_drift`, which does not exist in the built-in metric catalogue.
The correct skill behavior: detect absence at preflight, offer to scaffold.

**Commands:**
```bash
# Step 1 — preflight confirms absence
aidrin list | grep data_drift || echo "absent"
# → "absent"

# Step 2 — scaffold (CLI path; MCP uses create_custom_metric)
aidrin add-custom-module data_drift --dir /path/to/project/

# Step 3 — implement metric() in the generated CustomDR class, then run
aidrin run custom /path/to/project/data_drift.py examples/sample_data/csv/adult.csv metric
```

**Outcome:**
- `aidrin list | grep data_drift` returned nothing (absence confirmed).
- `aidrin add-custom-module data_drift --dir <dir>` exited 0, printed the template path and next-step instructions.
- Unedited scaffold ran immediately and returned `{"message": "Placeholder metric. Implement your logic here."}`, exit 0.

**PASS** — absent-metric detection + scaffold + run path works end-to-end.
Skill correctly says to offer `create_custom_metric` / `aidrin add-custom-module`
when `list_metrics()` / `aidrin list` does not contain the requested metric.

---

## Scenario 4: Error isolation — deliberate bad column

**Command:**
```bash
uv run aidrin run class-imbalance examples/sample_data/csv/adult.csv NoSuchColumn; echo "exit=$?"
```

**Outcome:**
```json
{"Error": "Target feature 'NoSuchColumn' not found in the dataset", "ErrorType": "Validation Error", ...}
exit=0
```

**Important finding:** `aidrin run` always exits 0, even on validation errors — errors are encoded in the JSON output body rather than the exit code. The skill's Step 7 instruction to "record as 'Not run: <reason>' and continue" is the correct pattern, but it cannot use exit-code detection to identify failures. The skill must inspect the JSON output for an `"Error"` key.

**PASS with caveat** — error isolation works at the JSON-body level. The skill's workflow handles this correctly by running metrics individually and inspecting output, but the metrics.md and SKILL.md do not explicitly document the always-exit-0 behavior. Skill authors should be aware when writing post-run logic.

---

## Summary

| Scenario | Result |
|---|---|
| 1. Training intent (CSV batch + per-metric run) | PASS |
| 2. Non-CSV schema read + metric run (JSON) | PASS |
| 3. Absent metric (`data_drift`) → scaffold + run end-to-end | PASS |
| 4. Error isolation — bad column, exit code behavior | PASS (with caveat: always exits 0) |

All core building blocks work. One behavioral note: `aidrin run` always exits 0 regardless of validation errors; errors are indicated only in the JSON body (`"ErrorType": "Validation Error"`). The skill's per-metric isolation pattern handles this correctly in practice, but skill authors should inspect JSON output rather than relying on exit codes.
