"""Unit tests for custom data loaders and read_file integration."""

from __future__ import annotations

import os
import textwrap

import pandas as pd
import pytest

from aidrin.file_handling.custom_loader import (
    CustomLoaderError,
    load_dataframe,
    parse_loader_spec,
    using_custom_loader,
)
from aidrin.file_handling.file_parser import read_file


def _write_loader(tmpdir: str, name: str, body: str) -> str:
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(body))
    return path


class TestParseLoaderSpec:
    def test_valid_spec(self):
        path, func = parse_loader_spec("loaders/root.py:load")
        assert path == "loaders/root.py"
        assert func == "load"

    def test_invalid_spec(self):
        with pytest.raises(CustomLoaderError, match="path/to/loader.py:function"):
            parse_loader_spec("nope")


class TestLoadDataframeErrors:
    def test_missing_file(self, tmp_path):
        spec = str(tmp_path / "missing.py") + ":load"
        with pytest.raises(CustomLoaderError) as exc:
            load_dataframe(spec, "data.root")
        msg = str(exc.value)
        assert "Custom loader" in msg
        assert "missing.py:load" in msg or "missing.py" in msg
        assert "data.root" in msg
        assert "not found" in msg.lower()

    def test_missing_function(self, tmp_path):
        path = _write_loader(
            str(tmp_path),
            "bad_fn.py",
            """
            import pandas as pd
            def other(path, **kwargs):
                return pd.DataFrame({"a": [1]})
            """,
        )
        spec = f"{path}:load"
        with pytest.raises(CustomLoaderError) as exc:
            load_dataframe(spec, "sample.csv")
        msg = str(exc.value)
        assert "Custom loader" in msg
        assert "sample.csv" in msg
        assert "not found or not callable" in msg

    def test_import_failure(self, tmp_path):
        path = _write_loader(
            str(tmp_path),
            "bad_import.py",
            """
            import definitely_not_a_real_module_xyz  # noqa: F401
            def load(path, **kwargs):
                return None
            """,
        )
        spec = f"{path}:load"
        with pytest.raises(CustomLoaderError) as exc:
            load_dataframe(spec, "sample.root")
        msg = str(exc.value)
        assert "Custom loader" in msg
        assert "sample.root" in msg
        assert "ModuleNotFoundError" in msg

    def test_exception_inside_load(self, tmp_path):
        path = _write_loader(
            str(tmp_path),
            "raises.py",
            """
            def load(path, **kwargs):
                raise ValueError("tree 'foo' not found")
            """,
        )
        spec = f"{path}:load"
        with pytest.raises(CustomLoaderError) as exc:
            load_dataframe(spec, "sample.root")
        msg = str(exc.value)
        assert "Custom loader" in msg
        assert "sample.root" in msg
        assert "ValueError" in msg
        assert "tree 'foo' not found" in msg

    def test_non_dataframe_return(self, tmp_path):
        path = _write_loader(
            str(tmp_path),
            "none_ret.py",
            """
            def load(path, **kwargs):
                return None
            """,
        )
        spec = f"{path}:load"
        with pytest.raises(CustomLoaderError) as exc:
            load_dataframe(spec, "x.csv")
        msg = str(exc.value)
        assert "returned None" in msg
        assert "Custom loader" in msg
        assert "x.csv" in msg


class TestLoadDataframeSuccess:
    def test_fake_loader_any_path(self, tmp_path):
        path = _write_loader(
            str(tmp_path),
            "fake.py",
            """
            import pandas as pd
            def load(path, **kwargs):
                return pd.DataFrame({"col_a": [1, 2], "col_b": ["x", "y"]})
            """,
        )
        # Unknown extension path — loader still runs
        dataset = str(tmp_path / "ignored.root")
        df = load_dataframe(f"{path}:load", dataset)
        assert list(df.columns) == ["col_a", "col_b"]
        assert len(df) == 2


class TestReadFileWithLoader:
    def test_unknown_ext_with_loader_context(self, tmp_path):
        path = _write_loader(
            str(tmp_path),
            "ctx.py",
            """
            import pandas as pd
            def load(path, **kwargs):
                return pd.DataFrame({"from_loader": [10, 20, 30]})
            """,
        )
        dataset = str(tmp_path / "weird.ext")
        dataset_path = open(dataset, "w", encoding="utf-8")
        dataset_path.write("placeholder")
        dataset_path.close()

        with using_custom_loader(f"{path}:load"):
            df = read_file((dataset, "weird.ext", ".ext"))
        assert isinstance(df, pd.DataFrame)
        assert "from_loader" in df.columns

    def test_loader_error_raises_explicit_message(self, tmp_path):
        path = _write_loader(
            str(tmp_path),
            "boom.py",
            """
            def load(path, **kwargs):
                raise RuntimeError("boom")
            """,
        )
        dataset = str(tmp_path / "data.bin")
        with open(dataset, "wb") as handle:
            handle.write(b"x")

        with pytest.raises(CustomLoaderError) as exc:
            read_file(
                (dataset, "data.bin", ".bin"),
                loader=f"{path}:load",
            )
        result = str(exc.value)
        assert "Custom loader" in result
        assert "RuntimeError" in result
        assert "boom" in result

    def test_without_loader_unknown_ext_returns_none(self, tmp_path):
        dataset = str(tmp_path / "data.root")
        with open(dataset, "wb") as handle:
            handle.write(b"x")
        assert read_file((dataset, "data.root", ".root")) is None

    def test_embedded_loader_in_file_info_works_without_context(self, tmp_path):
        """Celery packs custom_loader_spec into file_info; no Flask session."""
        path = _write_loader(
            str(tmp_path),
            "embed.py",
            """
            import pandas as pd
            def load(path, **kwargs):
                return pd.DataFrame({"embedded": [1, 2]})
            """,
        )
        dataset = str(tmp_path / "data.root")
        with open(dataset, "wb") as handle:
            handle.write(b"x")
        df = read_file((dataset, "data.root", ".root", f"{path}:load"))
        assert isinstance(df, pd.DataFrame)
        assert list(df["embedded"]) == [1, 2]


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("uproot") is None,
    reason="uproot not installed",
)
def test_uproot_optional_roundtrip(tmp_path):
    uproot = pytest.importorskip("uproot")
    import numpy as np

    root_path = tmp_path / "tiny.root"
    with uproot.recreate(str(root_path)) as f:
        f["tree"] = {"x": np.array([1.0, 2.0, 3.0]), "y": np.array([4, 5, 6])}

    loader = _write_loader(
        str(tmp_path),
        "root_load.py",
        """
        import uproot
        def load(path, **kwargs):
            with uproot.open(path) as f:
                return f[kwargs.get("tree", "tree")].arrays(library="pd")
        """,
    )
    df = load_dataframe(f"{loader}:load", str(root_path))
    assert list(df.columns) == ["x", "y"]
    assert len(df) == 3
