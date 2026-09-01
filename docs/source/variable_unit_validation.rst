.. _variable_unit_validation:

Variable Unit Validation
========================

``variable-unit-validation`` checks whether every logical dataset variable has
usable measurement-unit metadata. It is a metadata-readiness check: it does not
inspect values to infer units, convert data, verify that a unit is physically
appropriate, or rewrite the source file.

Every variable must be classified as one of:

- a unit recognized by Pint, such as ``m/s^2``;
- dimensionless, written as ``1``; or
- ``not_applicable`` for identifiers, labels, free text, and similar fields.

Mapping schema
--------------

Mappings are JSON objects keyed by the exact logical variable name. Each entry
contains exactly one of ``unit`` or ``status``:

.. code-block:: json

   {
     "acceleration": {"unit": "m/s^2"},
     "normalized_score": {"unit": "1"},
     "station_id": {"status": "not_applicable"}
   }

Unknown keys are reported as stale mapping variables and make
``all_variables_ready`` false. Malformed entries are rejected. Mapping files
must be UTF-8 JSON.

Discovery and precedence
------------------------

AIDRIN recognizes logical columns in tabular formats, logical columns in
pandas/PyTables HDF5 stores, native HDF5 dataset paths, and Parquet fields.
Native HDF5 ``units`` and ``unit`` attributes and Parquet field metadata with
the same keys are recognized. Variable names may also use a trailing
parenthesized or bracketed annotation, for example ``velocity (m/s)`` or
``velocity [m/s]``. Text elsewhere in a name is not treated as a unit, and the
complete original name remains the mapping key.

Declarations are resolved in this order:

1. explicit mapping;
2. native HDF5 or Parquet metadata; and
3. trailing name annotation.

An explicit mapping overrides lower-priority declarations and leaves an
override warning in the result. Equivalent aliases such as ``m/s`` and
``meter/second`` agree. Scale-different declarations such as ``m/s`` and
``km/h`` conflict until an explicit mapping resolves them.

Ambiguous ``g``
---------------

Bare ``g`` is rejected as ambiguous before Pint interprets it as gram. Use
``gram`` for mass. For standard acceleration of gravity, use ``[g]``, ``g_0``,
or ``standard_gravity``. A trailing name annotation such as
``acceleration [g]`` is normalized to ``standard_gravity``.

Interfaces
----------

CLI and remote CLI:

.. code-block:: bash

   aidrin run variable-unit-validation data.csv --units-file units.json
   aidrin run variable-unit-validation data.csv --units-json '{"speed":{"unit":"m/s"}}'
   aidrin remote run variable-unit-validation /scratch/data.csv \
     --units-file /scratch/units.json

``--units-json`` and ``--units-file`` are mutually exclusive. A mapping-file
path is resolved on the execution host, so the remote form names a path on the
Globus Compute endpoint.

Python:

.. code-block:: python

   from aidrin import calculate_variable_unit_validation

   result = calculate_variable_unit_validation(
       ("data.csv", "data.csv", ".csv"),
       {"speed": {"unit": "m/s"}},
   )

Batch configuration accepts either an inline ``unit_declarations`` object or
``units_file``. The MCP server exposes the dedicated ``verify_variable_units``
tool; ``run_aidrin_metric`` also accepts ``unit_declarations_json`` and
``units_file``.

In the web Data Structure panel, **Verify variable units** opens a searchable,
paginated editor. Embedded and name-based declarations are prefilled; other
variables remain unclassified until edited. JSON import and export happen in
the browser, and edits are request-local. Globus workers advertise the
``variable_unit_validation_v1`` capability; older workers leave the control
disabled with an upgrade message.

Results
-------

The result includes ``coverage_score``, ``validity_score``,
``all_variables_ready``, classification counts, one record per variable,
override warnings, lower-priority declarations, and unknown mapping variables.
Coverage measures variables with any declaration. Validity measures variables
that resolve to a recognized unit, ``1``, or ``not_applicable``. An empty
logical schema returns null scores and ``all_variables_ready`` false.
