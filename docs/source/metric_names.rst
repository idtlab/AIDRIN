.. |yes| raw:: html

   <i class="fa fa-check support-yes" title="available" role="img" aria-label="available"></i>

.. |no| raw:: html

   <i class="fa fa-times support-no" title="not available" role="img" aria-label="not available"></i>

.. _metric_names:

Metric Names Across Interfaces
==============================

The same metric is named differently in the web interface, on the command line,
and in the Python library, and not every metric is reachable from every
interface. This page maps between them. For what each metric measures and
returns, see :ref:`web_usage`; for how to invoke them, see :ref:`cli_usage` and
:ref:`python_api`.

Categories
----------

Metrics are grouped into categories. ``aidrin list --category`` accepts five:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Category
     - Covers
   * - ``data-quality``
     - Completeness, duplicates, outliers, and custom validity rules
   * - ``data-structure``
     - Constant features, collinearity, and distribution shape
   * - ``impact-of-data-on-AI``
     - Correlation and feature relevance
   * - ``fairness-and-bias``
     - Class imbalance, representation, and statistical parity
   * - ``data-governance``
     - Re-identification risk, HIPAA identifiers, and differential privacy

The web interface groups the same metrics into **six** dimensions. The sixth,
Understandability and Usability, has no CLI category because the FAIR metrics
that make it up run only in the web interface.

Naming conventions
------------------

Each interface has its own spelling of the same metric:

- The **web interface** uses display labels in title case, such as
  *Duplicates by Selected Features*.
- The **command line** uses lower-case dash-separated names, such as
  ``duplicity-by-features``. These are the names ``aidrin list`` prints and
  ``aidrin run`` accepts.
- The **Python library** prefixes the metric with ``calculate_`` or, for the
  privacy metrics, ``compute_``, such as ``calculate_duplicity_by_features``.

Arguments follow the interface too. On the command line they are positional, in
the order shown by ``aidrin run <metric> -h``, except the completeness family
(``row-level-completeness``, ``duplicity-by-features``,
``feature-coverage-ratio``, ``temporal-completeness``, ``null-count-trend``),
which takes named ``--flags``. The library takes keyword arguments whose names
do not always match the command line: ``class-imbalance`` takes
``target-column`` on the command line and ``column`` in the library.

.. warning::

   ``aidrin run`` accepts only the dash form. ``aidrin run
   row_level_completeness`` fails with ``invalid choice``. The shortcut form
   without ``run``, such as ``aidrin row_level_completeness``, accepts either
   spelling.

The mapping
-----------

|yes| means available, |no| means not. ``Globus`` means the metric can be dispatched to a remote Globus Compute
endpoint from the web interface; that path runs through the Python library, so
it covers the same set. ``MCP`` means the metric is reachable through the MCP
server, which dispatches on the same registry as the command line.

.. list-table::
   :header-rows: 1
   :widths: 26 22 30 11 11

   * - Web interface
     - ``aidrin run``
     - Python library
     - Globus
     - MCP
   * - Column-Level Completeness
     - ``completeness``
     - ``calculate_completeness``
     - |yes|
     - |yes|
   * - Row-Level Completeness
     - ``row-level-completeness``
     - ``calculate_row_level_completeness``
     - |yes|
     - |yes|
   * - Feature Coverage Ratio
     - ``feature-coverage-ratio``
     - ``calculate_feature_coverage_ratio``
     - |yes|
     - |yes|
   * - Temporal Completeness
     - ``temporal-completeness``
     - ``calculate_temporal_completeness``
     - |yes|
     - |yes|
   * - Null Count Trend
     - ``null-count-trend``
     - ``calculate_null_count_trend``
     - |yes|
     - |yes|
   * - Duplicates
     - ``duplicity``
     - ``calculate_duplicates``
     - |yes|
     - |yes|
   * - Duplicates by Selected Features
     - ``duplicity-by-features``
     - ``calculate_duplicity_by_features``
     - |yes|
     - |yes|
   * - Outliers
     - ``outliers``
     - ``calculate_outliers``
     - |yes|
     - |yes|
   * - Custom Criteria Outliers
     - ``outliers-custom``
     - ``calculate_custom_outliers`` [#unexported]_
     - |no|
     - |yes|
   * - Constant Feature Count
     - ``constant-feature-count``
     - ``calculate_constant_feature_count``
     - |yes|
     - |yes|
   * - Max Pairwise Correlation
     - ``max-pairwise-correlation``
     - ``calculate_max_pairwise_correlation``
     - |yes|
     - |yes|
   * - Skewness
     - ``skewness``
     - ``calculate_skewness``
     - |yes|
     - |yes|
   * - Kurtosis
     - ``kurtosis``
     - ``calculate_kurtosis``
     - |yes|
     - |yes|
   * - Correlation Analysis
     - ``correlations``
     - ``calculate_correlations``
     - |yes|
     - |yes|
   * - Feature Relevance
     - ``feature-relevance``
     - ``calculate_feature_relevance``
     - |yes|
     - |yes|
   * - Class Imbalance
     - ``class-imbalance``
     - ``calculate_class_distribution``
     - |yes|
     - |yes|
   * - Statistical Rates
     - ``statistical-rates``
     - ``calculate_statistical_rates``
     - |yes|
     - |yes|
   * - Representation Rates
     - ``representation-rate``
     - ``calculate_representation_rate``
     - |yes|
     - |yes|
   * - k-Anonymity
     - ``k-anonymity``
     - ``compute_k_anonymity``
     - |yes|
     - |yes|
   * - l-Diversity
     - ``l-diversity``
     - ``compute_l_diversity``
     - |yes|
     - |yes|
   * - t-Closeness
     - ``t-closeness``
     - ``compute_t_closeness``
     - |yes|
     - |yes|
   * - Entropy Risk
     - ``entropy-risk``
     - ``compute_entropy_risk``
     - |yes|
     - |yes|
   * - Single Attribute Risk Score
     - ``single-attribute-risk``
     - |no|
     - |no|
     - |yes|
   * - Multiple Attribute Risk Score
     - ``multiple-attribute-risk``
     - |no|
     - |no|
     - |yes|
   * - Differential Privacy
     - ``differential-privacy``
     - |no|
     - |no|
     - |yes|
   * - HIPAA Compliance
     - ``hipaa-compliance``
     - |no|
     - |no|
     - |yes|
   * - Conditional Demographic Disparity
     - |no|
     - |no|
     - |no|
     - |no|
   * - FAIR Compliance Report
     - |no|
     - |no|
     - |no|
     - |no|

.. [#unexported] Importable as ``from aidrin import calculate_custom_outliers``,
   but absent from ``aidrin.__all__``, so ``import *`` will not pick it up.
   Globus dispatch does not include it, but the MCP server exposes it through
   its own ``run_custom_outlier_check`` tool.

.. warning::

   ``differential-privacy`` writes the noised dataset to ``noisy/noisy_data.csv``
   relative to the working directory, creating ``noisy/`` if needed. On the
   command line that is wherever you ran ``aidrin``; in the web interface it is
   on the server.

Custom Metrics and Remedies
----------------------------

AIDRIN supports user-authored metrics and remedies (a ``CustomDR`` class) 
and have no fixed catalogue entry,so they are not in the mapping table above. See
:ref:`web_usage_custom_metrics` for the web interface workflow, 
:ref:`cli_add_custom_module` for the CLI scaffold-and-run workflow, and
:ref:`aidrin_skill_tools` for the MCP equivalents.
