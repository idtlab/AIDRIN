# Unit Metadata Audit and Repair Across AIDRIN

## Product contract

AIDRIN provides one format-independent workflow:

1. Audit unit metadata already associated with every logical variable.
2. Let the user resolve missing or incorrect metadata.
3. Report deterministic syntax, ambiguity, conflict, and completeness findings.
4. Produce a complete sidecar JSON without modifying the source dataset.

The canonical sidecar is the only public unit-metadata input and output format.
This feature is unreleased, so no compatibility parser or deprecated mapping
format is retained.

LLM-assisted semantic detection and expected-schema comparison are deferred.
They must preserve deterministic findings, explain their evidence, and require
user confirmation rather than silently changing metadata.

## Implementation checklist

- [x] Replace declaration mappings with a complete, versioned sidecar.
- [x] Bind sidecars to the discovered logical schema with a fingerprint.
- [x] Preserve observed metadata separately from user resolutions.
- [x] Return separate classification, applicable-unit, and validity scores.
- [x] Use the same sidecar contract in Python, CLI, batch, MCP, remote, and web.
- [x] Replace the opt-in web check with an automatic audit and repair editor.
- [x] Preserve a Physical Unit draft while the user enters its unit.
- [x] Require deterministic revalidation before downloading edited metadata.
- [x] Publish and test a normative JSON Schema.
- [x] Complete full repository validation and final diff audit.

## Deterministic behavior

- Discover tabular columns and native HDF5 dataset paths without inferring units
  from values.
- Observe native HDF5 and Parquet unit metadata and trailing variable-name
  annotations.
- Parse units with Pint and report normalized units and dimensionality.
- Reject malformed units, ambiguous bare g, conflicting detections, incomplete
  sidecars, duplicate variables, and schema fingerprint mismatches.
- Represent every variable as unit, dimensionless, not applicable, or
  unresolved.
- Preserve the source file byte-for-byte.

## Validation

- Focused core, interface, web, MCP, remote, and Globus tests.
- Behavioral browser check of audit, Physical Unit selection, unit entry,
  backend validation, and sidecar download state.
- Full pytest, flake8, Prettier, strict Sphinx, JSON Schema, and wheel build
  gates before completion.
