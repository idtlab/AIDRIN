"""
Tests for BaseIngestionPlugin and the dynamic-loading mechanism.

Mirrors the test style from test_hdf5_reader.py.
"""

import importlib.util
import sys
import textwrap
import types

if "pkg_resources" not in sys.modules:
    _pkg_resources = types.ModuleType("pkg_resources")

    class _Dist:
        def __init__(self):
            self.version = "0.0.0"

    _pkg_resources.get_distribution = lambda _name: _Dist()
    sys.modules["pkg_resources"] = _pkg_resources

import pandas as pd
import pytest

from aidrin.custom_readers.base_ingestion_plugin import BaseIngestionPlugin


# ---------------------------------------------------------------------------
# BaseIngestionPlugin contract
# ---------------------------------------------------------------------------

class TestBaseIngestionPlugin:
    def test_abstract_method_enforced(self):
        """Instantiating without implementing ingest() raises TypeError."""
        class Incomplete(BaseIngestionPlugin):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_valid_subclass_runs(self, tmp_path):
        csv_path = str(tmp_path / "data.csv")
        pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(csv_path, index=False)

        class CsvPlugin(BaseIngestionPlugin):
            def ingest(self, file_path: str) -> pd.DataFrame:
                return pd.read_csv(file_path)

        df = CsvPlugin().ingest(csv_path)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_validate_rejects_empty(self):
        class P(BaseIngestionPlugin):
            def ingest(self, file_path):
                return pd.DataFrame()

        with pytest.raises(ValueError, match="empty"):
            P().validate(pd.DataFrame())

    def test_validate_rejects_none(self):
        class P(BaseIngestionPlugin):
            def ingest(self, file_path):
                return pd.DataFrame({"x": [1]})

        with pytest.raises(ValueError):
            P().validate(None)

    def test_validate_accepts_valid_dataframe(self):
        class P(BaseIngestionPlugin):
            def ingest(self, file_path):
                return pd.DataFrame({"x": [1]})

        assert P().validate(pd.DataFrame({"x": [1, 2]})) is True

    def test_kwargs_stored(self):
        class P(BaseIngestionPlugin):
            def ingest(self, file_path):
                return pd.DataFrame({"x": [1]})

        p = P(encoding="utf-8", delimiter=",")
        assert p.kwargs["encoding"] == "utf-8"

    def test_describe_returns_class_name(self):
        class MyReader(BaseIngestionPlugin):
            def ingest(self, file_path):
                return pd.DataFrame({"x": [1]})

        assert "MyReader" in MyReader().describe()


# ---------------------------------------------------------------------------
# Dynamic loading — mirrors the importlib path in main.py
# ---------------------------------------------------------------------------

class TestPluginDynamicLoading:
    def test_subclass_discovered_via_importlib(self, tmp_path):
        """importlib can find a BaseIngestionPlugin subclass in a user file."""
        code = textwrap.dedent("""
            import pandas as pd
            from aidrin.custom_readers.base_ingestion_plugin import BaseIngestionPlugin

            class DynamicReader(BaseIngestionPlugin):
                def ingest(self, file_path: str) -> pd.DataFrame:
                    return pd.DataFrame({"loaded": [True]})
        """)
        plugin_path = str(tmp_path / "dynamic_reader.py")
        with open(plugin_path, "w") as f:
            f.write(code)

        spec = importlib.util.spec_from_file_location("dynamic_reader", plugin_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        plugin_class = next(
            (
                getattr(module, n)
                for n in dir(module)
                if isinstance(getattr(module, n), type)
                and issubclass(getattr(module, n), BaseIngestionPlugin)
                and getattr(module, n) is not BaseIngestionPlugin
            ),
            None,
        )
        assert plugin_class is not None
        assert plugin_class.__name__ == "DynamicReader"

    def test_dynamic_ingest_executes_correctly(self, tmp_path):
        csv_path = str(tmp_path / "data.csv")
        pd.DataFrame({"val": [10, 20, 30]}).to_csv(csv_path, index=False)

        code = textwrap.dedent("""
            import pandas as pd
            from aidrin.custom_readers.base_ingestion_plugin import BaseIngestionPlugin

            class CSVPlugin(BaseIngestionPlugin):
                def ingest(self, file_path: str) -> pd.DataFrame:
                    return pd.read_csv(file_path)
        """)
        plugin_path = str(tmp_path / "csv_plugin.py")
        with open(plugin_path, "w") as f:
            f.write(code)

        spec = importlib.util.spec_from_file_location("csv_plugin", plugin_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        cls = getattr(module, "CSVPlugin")
        df = cls().ingest(csv_path)
        assert len(df) == 3
        assert "val" in df.columns
