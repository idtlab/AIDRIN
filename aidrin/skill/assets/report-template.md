# Dataset AI-Readiness Report: [dataset name]

## 1. Dataset overview
- Path / format:
- Rows / columns:
- Schema (from AIDRIN's parser): [column : dtype, ...]

## 2. Intended use
[The user's stated downstream goal, in their words.]

## 3. Confirmed column roles
> Privacy and fairness results below are conditional on these role assignments.
- Target column:
- Sensitive attribute(s):
- Quasi-identifiers:
- ID column:
[Note any column whose role was uncertain or user-corrected.]

## 4. Findings by dimension
For each metric run: score(s) + what the value indicates (direction). Mark any
metric that could not run as "Not run: [reason]".

### Data quality
### Impact on AI
### Fairness & bias
### Data governance
### Privacy

## 5. Domain-grounded findings (if applicable)
[Only include if the agentic pipeline ran (Workflow Step 8).]
- Model: [OpenAI model chosen in Step 2, used for retrieval/execution/scoring/remediation]
[One entry per domain question from the returned JSON.]
- Question:
- Answer / finding: [from the execution result]
- Complexity / confidence: [from the complexity scorer]
- Suggested remediation: [from the remediation generator]
- Source: [resource path that was indexed]

## 6. Risks & flags
[Notable extremes worth attention — e.g. k=1 groups, very low completeness,
strong group representation skew.]

## 7. Suggested next steps
[Non-prescriptive. The readiness decision belongs to the user.]

## 8. Appendix
- Raw metric outputs: [paths to saved JSON]
- Calls/commands executed (the plan): [list — MCP tool calls or CLI commands]
- Remedied dataset (if applied): [path to output CSV]
