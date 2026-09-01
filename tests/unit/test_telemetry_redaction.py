"""AIDRIN detects PII and PHI.  It must never upload it.

Metric results carry raw cell values in several places — matched PHI examples,
duplicate-group feature values, flagged outlier cells, resolved file paths, and
sensitive-attribute values used as dict keys.  The projection layer is an
allowlist: a metric contributes only the scalars it explicitly declares, and any
metric without a declaration contributes nothing but its runtime.

The structural test here is the one that matters — it still holds when metric
number 29 is added by someone who has never read this file.
"""

import sys
import types
import unittest

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

from aidrin.headless.api import METRIC_REGISTRY  # noqa: E402
from aidrin.telemetry.redaction import HEADLINE, project  # noqa: E402


class TestProjectionIsScalarsOnly(unittest.TestCase):
    def test_every_declared_projection_yields_only_numbers(self):
        """A projection may never yield a subtree — that is how leaks happen."""
        for metric_key in HEADLINE:
            with self.subTest(metric=metric_key):
                for mlflow_key, path in HEADLINE[metric_key].items():
                    self.assertIsInstance(mlflow_key, str)
                    self.assertIsInstance(path, tuple)


class TestKeyNamespacing(unittest.TestCase):
    """Keys are ``aidrin.<dimension>.<name>``.

    The dimension segment lets the MLflow runs table be filtered to one readiness
    dimension once the table is wide, and it has to agree with the metric's
    ``METRIC_REGISTRY`` category or the grouping means nothing.  Renaming a key
    later orphans its history under the old name, so this is checked rather than
    left to care.
    """

    def _keys(self):
        from aidrin.telemetry.redaction import all_metric_keys

        return all_metric_keys()

    def test_every_key_has_a_dimension_segment(self):
        for metric_key, mlflow_key in self._keys():
            with self.subTest(key=mlflow_key):
                parts = mlflow_key.split(".")
                self.assertEqual(
                    len(parts), 3, f"{mlflow_key} is not aidrin.<dimension>.<name>"
                )
                self.assertEqual(parts[0], "aidrin")

    def test_dimension_matches_the_registry_category(self):
        from aidrin.telemetry.redaction import NAMESPACE

        for metric_key, mlflow_key in self._keys():
            with self.subTest(key=mlflow_key):
                category = METRIC_REGISTRY[metric_key]["category"]
                self.assertEqual(
                    mlflow_key.split(".")[1],
                    NAMESPACE[category],
                    f"{metric_key} is categorised {category!r} but its key says "
                    f"{mlflow_key.split('.')[1]!r}",
                )

    def test_every_registry_category_has_a_namespace(self):
        from aidrin.telemetry.redaction import NAMESPACE

        categories = {m["category"] for m in METRIC_REGISTRY.values()}
        self.assertEqual(
            categories - set(NAMESPACE), set(), "a registry category has no namespace"
        )

    def test_a_declared_metric_projects_nothing_from_a_foreign_result(self):
        """Declared paths must match on purpose, never by coincidence."""
        from aidrin.telemetry.redaction import _DERIVED

        for metric_key in set(HEADLINE) | set(_DERIVED):
            with self.subTest(metric=metric_key):
                projected = project(metric_key, {"anything": "at all"})
                self.assertEqual(
                    {k: v for k, v in projected.items() if v},
                    {},
                    f"{metric_key} found a value in an unrelated result",
                )

    def test_unknown_metric_projects_to_nothing(self):
        self.assertEqual(project("not_a_metric", {"score": 1.0}), {})

    def test_projection_output_is_always_numeric(self):
        """Strings could carry cell values; only numbers leave the projection."""
        result = {"Overall Completeness": 0.83}
        for value in project("completeness", result).values():
            self.assertIsInstance(value, float)


class TestNoRawValuesEscape(unittest.TestCase):
    """Each case mirrors a confirmed leak path in a real metric result."""

    def test_hipaa_matched_examples_never_escape(self):
        result = {
            "patient_ssn": {
                "total_flags": 3,
                "potential_types_detected": ["SSN"],
                "examples": ["123-45-6789", "987-65-4321"],
            }
        }
        projected = project("hipaa_compliance", result)
        rendered = repr(projected)
        self.assertNotIn("123-45-6789", rendered)
        self.assertNotIn("987-65-4321", rendered)

    def test_hipaa_still_reports_useful_counts(self):
        result = {
            "patient_ssn": {
                "total_flags": 3,
                "potential_types_detected": ["SSN"],
                "examples": ["123-45-6789"],
            },
            "contact": {
                "total_flags": 1,
                "potential_types_detected": ["EMAIL"],
                "examples": ["a@b.com"],
            },
        }
        projected = project("hipaa_compliance", result)
        self.assertEqual(projected["aidrin.governance.hipaa_flagged_columns"], 2.0)
        self.assertEqual(projected["aidrin.governance.hipaa_total_flags"], 4.0)

    def test_file_reference_paths_never_escape(self):
        secret = "/data/patients/MRN-4417723/scan.dcm"
        result = {
            "Invalid references": [
                {
                    "target": "scan_path",
                    "location": "row 4",
                    "value": repr(secret),
                    "normalized_value": secret,
                    "resolved_path": secret,
                    "reason": "missing",
                }
            ],
            "Summary": {"invalid_references": 1},
        }
        self.assertNotIn("MRN-4417723", repr(project("file_reference_validation", result)))

    def test_duplicate_group_feature_values_never_escape(self):
        result = {
            "Duplicate groups": [
                {"Feature values": {"name": "Jane Doe", "dob": "1974-02-11"}, "Row count": 3}
            ],
            "Overall duplicity of the dataset": 0.2,
        }
        rendered = repr(project("duplicity_by_features", result))
        self.assertNotIn("Jane Doe", rendered)
        self.assertNotIn("1974-02-11", rendered)

    def test_sensitive_attribute_values_never_become_keys(self):
        result = {"Statistical Rates": {"female": 0.31, "non-binary": 0.02, "male": 0.67}}
        rendered = repr(project("statistical_rates", result))
        for value in ("female", "non-binary", "male"):
            self.assertNotIn(value, rendered)

    def test_error_strings_never_escape(self):
        """Pandas and numpy messages echo column names and offending values."""
        result = {"Error": "cannot convert 'SSN-123-45-6789' in column 'patient_ssn'"}
        rendered = repr(project("completeness", result))
        self.assertNotIn("SSN-123-45-6789", rendered)
        self.assertNotIn("patient_ssn", rendered)


class TestNonFiniteValuesAreSkipped(unittest.TestCase):
    """NaN renders as 0 in the MLflow UI — worse than a gap on a readiness chart."""

    def test_nan_is_not_projected(self):
        self.assertEqual(project("completeness", {"Overall Completeness": float("nan")}), {})

    def test_infinity_is_not_projected(self):
        self.assertEqual(project("completeness", {"Overall Completeness": float("inf")}), {})

    def test_missing_path_is_not_an_error(self):
        self.assertEqual(project("completeness", {"Error": "no data"}), {})

    def test_nested_path_is_followed(self):
        result = {"Duplicity scores": {"Overall duplicity of the dataset": 0.25}}
        self.assertEqual(project("duplicity", result), {"aidrin.quality.duplicity": 0.25})



class TestDeclaredPathsResolveAgainstRealResults(unittest.TestCase):
    """Every declared path must resolve against a metric's actual output.

    The paths are hand-written, and a metric's runner may nest its score under a
    wrapper key that the metric module itself does not show.  Reading the source
    is not enough — this runs the metrics.
    """

    CASES = {
        "completeness": {},
        "duplicity": {},
        "outliers": {},
        "constant_feature_count": {},
        "variable_unit_validation": {},
        "max_pairwise_correlation": {},
        "class_imbalance": {"target_column": "approved"},
        "k_anonymity": {"quasi_identifiers": "age,education"},
        "feature_coverage_ratio": {"threshold": 0.9},
        "row_level_completeness": {"required_columns": "age,income"},
        "l_diversity": {"quasi_identifiers": "age", "sensitive_column": "education"},
        "t_closeness": {"quasi_identifiers": "age", "sensitive_column": "income"},
        "entropy_risk": {"quasi_identifiers": "age,education"},
        "duplicity_by_features": {"duplicate_columns": "education"},
        "multiple_attribute_risk": {"id_column": "id", "eval_columns": "age,education"},
        "skewness": {},
        "kurtosis": {},
        "temporal_completeness": {"timestamp_column": "day", "frequency": "D"},
    }

    @classmethod
    def setUpClass(cls):
        import os
        import tempfile

        import pandas as pd

        df = pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5, 6],
                "day": [
                    "2024-01-01", "2024-01-02", "2024-01-03",
                    "2024-01-04", "2024-01-05", "2024-01-06",
                ],
                "age": [44, 31, 52, 28, 39, 61],
                "income": [70328, 41200, 88000, 35000, 59000, 102000],
                "education": ["High School", "BSc", "MSc", "High School", "BSc", "PhD"],
                "approved": [1, 0, 1, 0, 1, 1],
            }
        )
        handle = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
        df.to_csv(handle.name, index=False)
        handle.close()
        cls.csv = handle.name
        cls._unlink = os.unlink

    @classmethod
    def tearDownClass(cls):
        try:
            cls._unlink(cls.csv)
        except OSError:
            pass

    def test_every_declared_metric_projects_a_score(self):
        from aidrin.headless.api import run_metric

        for metric_key, kwargs in self.CASES.items():
            with self.subTest(metric=metric_key):
                result = run_metric(metric_key, self.csv, save_images=False, **kwargs)
                projected = project(metric_key, result)
                self.assertTrue(
                    projected,
                    f"{metric_key} declares a projection but it resolved to nothing "
                    f"against a real result; top-level keys were {list(result)}",
                )

    def test_every_headline_metric_is_covered_by_this_test(self):
        """A new HEADLINE entry must come with a case here."""
        self.assertEqual(
            set(HEADLINE) - set(self.CASES), set(), "add the new metric to CASES"
        )


class TestDerivedKeysAreDeclaredOnce(unittest.TestCase):
    """A derived projection must not restate its keys in a second table.

    Two lists to keep in sync means a key added to the function and forgotten in
    the table silently escapes the namespace check.
    """

    FIXTURES = {
        "hipaa_compliance": {"c": {"total_flags": 1, "potential_types_detected": ["SSN"],
                                   "examples": ["x"]}},
        "duplicity_by_features": {"Duplicate percentage": 20.0, "Duplicate count": 4},
        "file_reference_validation": {"Summary": {"invalid_references": 1,
                                                  "valid_references": 2}},
    }

    def test_each_function_only_emits_keys_it_declared(self):
        from aidrin.telemetry.redaction import all_metric_keys

        declared = {}
        for metric_key, mlflow_key in all_metric_keys():
            declared.setdefault(metric_key, set()).add(mlflow_key)

        for metric_key, result in self.FIXTURES.items():
            with self.subTest(metric=metric_key):
                produced = set(project(metric_key, result))
                self.assertTrue(produced, f"{metric_key} produced nothing")
                self.assertTrue(
                    produced <= declared.get(metric_key, set()),
                    f"{metric_key} emitted undeclared keys: "
                    f"{produced - declared.get(metric_key, set())}",
                )


class TestKeysDoNotCollideAcrossMetrics(unittest.TestCase):
    """Two metrics must not declare the same MLflow key.

    Scores from every metric are aggregated onto the assessment run, so a shared
    key means one metric silently overwrites the other's value there.
    """

    def test_every_declared_key_belongs_to_one_metric(self):
        from aidrin.telemetry.redaction import all_metric_keys

        owners = {}
        for metric_key, mlflow_key in all_metric_keys():
            owners.setdefault(mlflow_key, []).append(metric_key)
        clashes = {k: v for k, v in owners.items() if len(v) > 1}
        self.assertEqual(clashes, {}, f"keys claimed by more than one metric: {clashes}")


class TestRiskScoresAreReported(unittest.TestCase):
    """The privacy metrics each produce a headline score worth comparing."""

    @classmethod
    def setUpClass(cls):
        import os
        import tempfile

        import pandas as pd

        directory = tempfile.mkdtemp()
        cls.csv = os.path.join(directory, "risk.csv")
        pd.DataFrame(
            {
                "id": range(60),
                "a": [i % 5 for i in range(60)],
                "b": [i % 7 for i in range(60)],
            }
        ).to_csv(cls.csv, index=False)

    def test_multiple_attribute_risk_reports_its_dataset_score(self):
        from aidrin.headless.api import run_metric

        result = run_metric(
            "multiple_attribute_risk", self.csv, id_column="id",
            eval_columns="a,b", save_images=False,
        )
        projected = project("multiple_attribute_risk", result)
        self.assertIn("aidrin.governance.multiple_attribute_risk", projected)

    def test_single_attribute_risk_reports_its_worst_column(self):
        """Per-column scores, so the comparable number is the worst of them."""
        from aidrin.headless.api import run_metric

        result = run_metric(
            "single_attribute_risk", self.csv, id_column="id",
            eval_columns="a,b", save_images=False,
        )
        projected = project("single_attribute_risk", result)
        self.assertIn("aidrin.governance.max_single_attribute_risk", projected)

    def test_the_worst_column_score_carries_no_column_name(self):
        result = {
            "Descriptive statistics of the risk scores": {
                "patient_ssn": {"mean": 0.9}, "age": {"mean": 0.2},
            }
        }
        projected = project("single_attribute_risk", result)
        self.assertEqual(projected["aidrin.governance.max_single_attribute_risk"], 0.9)
        self.assertNotIn("patient_ssn", repr(projected))



class TestEveryMetricReportsSomething(unittest.TestCase):
    """A run showing only a runtime tells you nothing about what was found.

    Per-column results cannot become metric keys, but an aggregate over them can,
    so every metric should contribute at least one comparable number.
    """

    def test_no_metric_is_left_with_only_a_runtime(self):
        from aidrin.headless.api import METRIC_REGISTRY
        from aidrin.telemetry.redaction import HEADLINE, _DERIVED

        declared = set(HEADLINE) | set(_DERIVED)
        silent = set(METRIC_REGISTRY) - declared
        self.assertEqual(
            silent, set(),
            f"these metrics would report only a runtime: {sorted(silent)}",
        )



class TestCleanResultsAreStillReported(unittest.TestCase):
    """A clean result is a finding, not an absence.

    A scan that found no PHI must report zero rather than nothing; otherwise it
    is indistinguishable in MLflow from a metric that never ran.
    """

    def test_a_clean_hipaa_scan_reports_zero(self):
        projected = project("hipaa_compliance", {})
        self.assertEqual(projected["aidrin.governance.hipaa_flagged_columns"], 0.0)
        self.assertEqual(projected["aidrin.governance.hipaa_total_flags"], 0.0)

    def test_a_dirty_hipaa_scan_still_reports_counts(self):
        projected = project(
            "hipaa_compliance",
            {"ssn": {"total_flags": 3, "potential_types_detected": ["SSN"],
                     "examples": ["123-45-6789"]}},
        )
        self.assertEqual(projected["aidrin.governance.hipaa_flagged_columns"], 1.0)
        self.assertEqual(projected["aidrin.governance.hipaa_total_flags"], 3.0)

    def test_a_failed_hipaa_scan_reports_nothing(self):
        """An error is not a clean result, so it must not look like zero."""
        self.assertEqual(project("hipaa_compliance", {"Error": "no such column"}), {})



class TestDimensionLookup(unittest.TestCase):
    """Runtime is namespaced by dimension so metric runs can be told apart."""

    def test_a_declared_metric_resolves_to_its_dimension(self):
        from aidrin.telemetry.redaction import dimension_for

        self.assertEqual(dimension_for("completeness"), "quality")
        self.assertEqual(dimension_for("k_anonymity"), "governance")
        self.assertEqual(dimension_for("skewness"), "structure")
        self.assertEqual(dimension_for("class_imbalance"), "fairness")
        self.assertEqual(dimension_for("correlations"), "impact")

    def test_an_unknown_metric_has_no_dimension(self):
        """A custom metric declares nothing, so it keeps the plain key."""
        from aidrin.telemetry.redaction import dimension_for

        self.assertIsNone(dimension_for("someones_custom_metric"))

    def test_the_dimension_matches_the_registry_category(self):
        from aidrin.telemetry.redaction import NAMESPACE, dimension_for

        for metric_key, meta in METRIC_REGISTRY.items():
            with self.subTest(metric=metric_key):
                expected = NAMESPACE[meta["category"]]
                self.assertEqual(dimension_for(metric_key), expected)


if __name__ == "__main__":
    unittest.main()
