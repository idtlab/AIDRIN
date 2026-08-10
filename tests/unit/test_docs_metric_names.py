"""Guards the metric mapping table in the documentation against drift.

``docs/source/metric_names.rst`` enumerates every metric by name outside the
code, so it can fall behind the registry silently. This asserts it has not.

Names only. Descriptions are not checked here, so a green run means the table
is complete, not that the prose is accurate.
"""

import os
import re
import unittest

from aidrin.headless.api import METRIC_REGISTRY

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING_RST = os.path.join(REPO_ROOT, "docs", "source", "metric_names.rst")

# The registry keys use underscores; every user-facing surface uses the dash
# form, because argparse registers the subcommands hyphenated.
REGISTRY_CLI_NAMES = {name.replace("_", "-") for name in METRIC_REGISTRY}

# Importable from ``aidrin`` but deliberately absent from ``__all__``. Documented
# as such in the mapping table; see the footnote there.
UNEXPORTED_BUT_DOCUMENTED = {"calculate_custom_outliers"}


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class TestMetricNameMapping(unittest.TestCase):
    """docs/source/metric_names.rst must list every metric, and no others."""

    @classmethod
    def setUpClass(cls):
        cls.text = _read(MAPPING_RST)
        # Second column of the list-table: the ``aidrin run`` name.
        cls.listed = set(re.findall(r"^     - ``([a-z0-9-]+)``$", cls.text, re.M))

    def test_every_registry_metric_is_mapped(self):
        missing = REGISTRY_CLI_NAMES - self.listed
        self.assertEqual(
            missing,
            set(),
            f"metric_names.rst is missing {sorted(missing)}. Add a row per new metric.",
        )

    def test_no_unknown_metrics_are_mapped(self):
        extra = self.listed - REGISTRY_CLI_NAMES
        self.assertEqual(
            extra,
            set(),
            f"metric_names.rst lists {sorted(extra)}, absent from METRIC_REGISTRY.",
        )

    def test_library_column_matches_the_package(self):
        import aidrin

        exported = set(aidrin.__all__) - {"__version__"}
        documented = set(re.findall(r"``((?:calculate|compute)_\w+)``", self.text))
        unknown = {name for name in documented if not hasattr(aidrin, name)}
        self.assertEqual(
            unknown,
            set(),
            f"metric_names.rst names {sorted(unknown)}, which are not importable from aidrin.",
        )
        missing = exported - documented
        self.assertEqual(
            missing,
            set(),
            f"metric_names.rst omits exported functions {sorted(missing)}.",
        )
        # Anything documented but unexported must be a known, annotated exception.
        undeclared = documented - exported - UNEXPORTED_BUT_DOCUMENTED
        self.assertEqual(
            undeclared,
            set(),
            f"{sorted(undeclared)} are documented but not in __all__; annotate or export them.",
        )


if __name__ == "__main__":
    unittest.main()
