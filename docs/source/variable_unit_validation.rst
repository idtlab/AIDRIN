.. _variable_unit_validation:

Unit Metadata Audit and Repair
==============================

The variable-unit-validation metric audits the unit metadata associated with
every logical variable in a dataset. It can apply user resolutions and return
a complete, reusable JSON sidecar. The source dataset is always read-only.

The workflow has three stages:

1. audit unit metadata already associated with the data;
2. resolve missing, invalid, ambiguous, or conflicting declarations; and
3. validate and download the complete sidecar.

The deterministic validator does not infer units from values, convert data, or
prove that a syntactically valid unit is physically appropriate. LLM-assisted
semantic suggestions and expected-schema comparison are separate future work.

Audit
-----

AIDRIN discovers logical columns in CSV, Excel, JSON, NPZ, and Parquet files;
logical columns in pandas/PyTables HDF5 stores; and native HDF5 dataset paths.
It recognizes:

- HDF5 unit and units attributes;
- Parquet field metadata using those keys; and
- trailing name annotations such as velocity (m/s) and acceleration [g].

The audit reports missing metadata, units that Pint cannot parse, ambiguous
bare g, and conflicting detected declarations. It does not inspect data values
to guess a unit.

Repair
------

Every variable has one resolution:

- unit with a Pint unit expression;
- dimensionless with unit 1;
- not_applicable for identifiers, timestamps, labels, and free text; or
- unresolved when review remains necessary.

A user resolution overrides detected metadata while preserving the observations
and recording a warning. The editor never embeds a correction in the source
file.

Canonical sidecar
-----------------

Every audit and repair result uses one format:

.. code-block:: json

   {
     "$schema": "https://aidrin.readthedocs.io/en/latest/_static/variable-unit-metadata.schema.json",
     "format": "aidrin.variable-unit-metadata",
     "version": 1,
     "unit_vocabulary": "pint",
     "dataset": {
       "name": "sensors.csv",
       "file_type": ".csv",
       "schema_fingerprint": "sha256:..."
     },
     "variables": [
       {
         "name": "temperature",
         "target_type": "column",
         "dtype": "float64",
         "observed": [],
         "resolution": {
           "kind": "unit",
           "unit": "degC",
           "source": "user"
         },
         "finding": {
           "status": "valid",
           "readiness": "ready",
           "normalized_unit": "°C",
           "dimensionality": "[temperature]",
           "message": "Unit is recognized by Pint.",
           "warnings": []
         }
       }
     ],
     "summary": {
       "counts": {
         "total": 1,
         "valid": 1,
         "missing": 0,
         "invalid": 0,
         "ambiguous": 0,
         "conflicting": 0,
         "dimensionless": 0,
         "not_applicable": 0
       },
       "classification_coverage": 1.0,
       "applicable_unit_coverage": 1.0,
       "metadata_validity": 1.0,
       "all_variables_ready": true
     }
   }

The sidecar contains every logical variable, including unresolved variables.
Its schema fingerprint binds it to the ordered names, target types, and data
types that AIDRIN discovered. Import fails when the fingerprint or complete
variable set differs, preventing accidental use with an incompatible dataset.
Renaming the dataset file alone does not invalidate the sidecar.

The normative schema is in
docs/source/_static/variable-unit-metadata.schema.json in the source tree and
at the URL in the sidecar's $schema field in rendered documentation.

Scores
------

classification_coverage
   Fraction of all variables that have some declaration. Invalid and ambiguous
   declarations are accounted for but not ready.

applicable_unit_coverage
   Fraction of variables not marked not_applicable that resolve to a valid unit
   or explicit dimensionless declaration.

metadata_validity
   Fraction of accounted-for variables that are ready.

all_variables_ready
   True only when every variable has a valid unit, is dimensionless, or is
   explicitly not applicable.

Unit parsing
------------

The web editor offers a curated list of common units, ranked using simple terms in the
variable name (for example, temperature or pressure). These are suggestions only: AIDRIN
does not silently assign a unit or infer one from the observed values. Users can select a
suggestion or enter any Pint-compatible unit expression.

Typed and imported unit strings are passed directly to Pint; AIDRIN does not maintain a
second vocabulary of human-readable aliases. Selecting a curated web suggestion stores
its Pint-compatible value in the sidecar and should cover most routine entry. Free-form
entry is intended for less common Pint expressions. A genuinely dataset-specific unit
that Pint does not define is preserved but flagged as unrecognized. The special ``[g]``
name annotation is treated as standard gravity so it remains distinct from the
deliberately ambiguous bare ``g``.

Pint parses and normalizes unit expressions. AIDRIN accepts forms such as
m/s^2, m/s², standard_gravity, g_0, and 1. Bare g is rejected as ambiguous:
use gram for mass or [g], g_0, or standard_gravity for acceleration. AIDRIN
also rejects m//s rather than accepting Pint's floor-division interpretation.

Interfaces
----------

Run an audit and print its sidecar:

.. code-block:: bash

   aidrin run variable-unit-validation data.csv

Revalidate a downloaded or edited sidecar:

.. code-block:: bash

   aidrin run variable-unit-validation data.csv \
     --unit-metadata-file data.units.json

The --unit-metadata-json option accepts the complete sidecar inline. A sidecar
path is resolved on the execution host, including for remote CLI execution.

Python:

.. code-block:: python

   from aidrin import calculate_variable_unit_validation

   audit = calculate_variable_unit_validation(
       ("data.csv", "data.csv", ".csv")
   )
   validated = calculate_variable_unit_validation(
       ("data.csv", "data.csv", ".csv"),
       audit,
   )

Batch configuration accepts unit_metadata or unit_metadata_file. The MCP tools
accept unit_metadata_json or unit_metadata_file. All interfaces return the same
canonical sidecar.

In the web app, open **Understandability** and select **Unit Metadata Audit**.
The initial audit runs automatically. Edits remain pending until
**Validate unit metadata** refreshes the deterministic findings. A validated
complete or incomplete sidecar can then be downloaded using a
dataset-name.units.json filename.

Globus workers advertise the variable_unit_metadata_v1 capability. Workers
without that capability leave the audit editor disabled and show an upgrade
message.
