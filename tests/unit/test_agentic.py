"""Unit tests for the aidrin agentic CLI subcommand."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import langchain_openai  # noqa: F401
    HAS_AGENTIC_DEPS = True
except ImportError:
    HAS_AGENTIC_DEPS = False

import numpy as np
import pandas as pd

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg


def _sample_df(n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "age": rng.integers(20, 70, size=n),
            "income": rng.integers(20_000, 100_000, size=n),
            "sex": rng.choice(["M", "F"], size=n),
            "label": rng.choice(["<=50K", ">50K"], size=n),
        }
    )


def _make_agentic_fixture(tmpdir: str, n: int = 30) -> Path:
    """Write data CSV, metadata TXT, and YAML config; return config path."""
    data_path = Path(tmpdir) / "data.csv"
    meta_path = Path(tmpdir) / "metadata.txt"
    cfg_path = Path(tmpdir) / "config.yaml"

    _sample_df(n).to_csv(data_path, index=False)
    meta_path.write_text("Test dataset: synthetic data for unit tests.", encoding="utf-8")

    cfg_path.write_text(
        textwrap.dedent(f"""\
            paths:
              data_csv: {data_path}
              metadata_csv: {meta_path}
            profiling:
              full_summary: true
        """),
        encoding="utf-8",
    )
    return cfg_path


def _run_cli(*argv: str) -> tuple[str, str, int]:
    """Invoke main() with the given argv, returning (stdout, stderr, exit_code)."""
    from aidrin.headless.cli import main

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    exit_code = 0
    with patch("sys.argv", ["aidrin", *argv]), \
         patch("sys.stdout", out_buf), \
         patch("sys.stderr", err_buf):
        try:
            main()
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    return out_buf.getvalue(), err_buf.getvalue(), exit_code


@unittest.skipUnless(HAS_AGENTIC_DEPS, "agentic extras not installed (pip install 'aidrin[agentic]')")
class TestAgenticCLI(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_agentic_run_exits_zero_with_minimal_config(self):
        cfg = _make_agentic_fixture(self.tmpdir)
        _, _, code = _run_cli("agentic", "run", "-c", str(cfg))
        self.assertEqual(code, 0)

    def test_agentic_run_produces_valid_json(self):
        cfg = _make_agentic_fixture(self.tmpdir)
        stdout, _, _ = _run_cli("agentic", "run", "-c", str(cfg))
        data = json.loads(stdout)
        self.assertIsInstance(data, dict)

    def test_agentic_run_output_has_profile_key(self):
        cfg = _make_agentic_fixture(self.tmpdir)
        stdout, _, _ = _run_cli("agentic", "run", "-c", str(cfg))
        data = json.loads(stdout)
        self.assertIn("profile", data)

    def test_agentic_run_output_has_token_usage(self):
        cfg = _make_agentic_fixture(self.tmpdir)
        stdout, _, _ = _run_cli("agentic", "run", "-c", str(cfg))
        data = json.loads(stdout)
        self.assertIn("token_usage", data)

    def test_agentic_run_profile_row_count(self):
        cfg = _make_agentic_fixture(self.tmpdir, n=20)
        stdout, _, _ = _run_cli("agentic", "run", "-c", str(cfg))
        data = json.loads(stdout)
        self.assertEqual(data["profile"]["summary"]["row_count"], 20)

    def test_agentic_run_writes_output_file(self):
        cfg = _make_agentic_fixture(self.tmpdir)
        out = Path(self.tmpdir) / "result.json"
        _run_cli("agentic", "run", "-c", str(cfg), "-o", str(out))
        self.assertTrue(out.exists())
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("profile", data)

    def test_agentic_run_missing_config_exits_nonzero(self):
        _, _, code = _run_cli("agentic", "run", "-c", "/nonexistent/config.yaml")
        self.assertNotEqual(code, 0)

    def test_agentic_build_index_missing_config_exits_nonzero(self):
        _, _, code = _run_cli("agentic", "build-index", "-c", "/nonexistent/config.yaml")
        self.assertNotEqual(code, 0)

    def test_agentic_run_midrun_import_error_is_not_misdiagnosed(self):
        """
        Regression test: an ImportError raised *during* a real run (e.g. the
        user's own data_loader.py imports a package that isn't installed)
        must surface as that real error, not get misdiagnosed as "agentic
        dependencies not installed" -- which would hide the actual problem
        and, on a real pipeline run with questions, discard any already-
        completed (paid-for) LLM work.
        """
        loader_path = Path(self.tmpdir) / "loader.py"
        loader_path.write_text(
            textwrap.dedent("""\
                import some_definitely_missing_package_xyz  # noqa: F401

                def load_dataset():
                    raise AssertionError("should never reach here")
            """),
            encoding="utf-8",
        )
        meta_path = Path(self.tmpdir) / "metadata.txt"
        meta_path.write_text("Test dataset.", encoding="utf-8")
        cfg_path = Path(self.tmpdir) / "config.yaml"
        cfg_path.write_text(
            textwrap.dedent(f"""\
                paths:
                  data_loader: "{loader_path}:load_dataset"
                  metadata_csv: {meta_path}
            """),
            encoding="utf-8",
        )

        _, stderr, code = _run_cli("agentic", "run", "-c", str(cfg_path))
        self.assertNotEqual(code, 0)
        self.assertNotIn("agentic dependencies not installed", stderr)
        self.assertIn("some_definitely_missing_package_xyz", stderr)

    def test_agentic_run_vector_build_failure_is_recorded_not_fatal(self):
        """
        Regression test: a vector index build failure must not abort the
        whole pipeline. It should be recorded as vector_store={"error": ...}
        while profile/queries/token_usage still come back from the rest of
        the run, rather than the exception propagating and discarding
        everything.
        """
        cfg = _make_agentic_fixture(self.tmpdir)
        with open(cfg, "a", encoding="utf-8") as fh:
            # No llm.embedding_model -- VectorDBBuilder's own construction
            # raises ValueError("llm.embedding_model must be set...").
            fh.write("\nvector_store:\n  dummy: true\n")

        stdout, _, code = _run_cli("agentic", "run", "-c", str(cfg))
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertIn("error", data["vector_store"])
        self.assertIn("embedding_model", data["vector_store"]["error"])
        self.assertIn("profile", data)
        self.assertIn("token_usage", data)

    def test_agentic_run_rebuilds_even_when_index_already_exists(self):
        """
        Regression test: `run` without --skip-vector must rebuild the index
        every time (matching --skip-vector's documented meaning: pass it to
        reuse the existing one), not silently skip the rebuild just because
        a directory of that name already exists -- which would leave new
        PDFs added to sources/ unindexed with no warning.
        """
        cfg = _make_agentic_fixture(self.tmpdir)
        index_dir = Path(self.tmpdir) / "test_index"
        index_dir.mkdir()
        # Simulate a pre-existing (possibly stale) index.
        (index_dir / "metadata.json").write_text("[]", encoding="utf-8")
        (index_dir / "embeddings.npy").write_bytes(b"")
        sources_dir = Path(self.tmpdir) / "sources"
        sources_dir.mkdir()
        (sources_dir / "doc.txt").write_text("hello", encoding="utf-8")
        with open(cfg, "a", encoding="utf-8") as fh:
            fh.write(
                textwrap.dedent(f"""\

                    llm:
                      embedding_model: test-embedding-model

                    vector_store:
                      sources:
                        - {sources_dir}
                      vector_store_dir: {index_dir}
                """)
            )

        with patch(
            "aidrin.agentic.vector_db_builder.VectorDBBuilder.build",
            return_value={"files_indexed": 0, "chunks": 0},
        ) as mock_build:
            _run_cli("agentic", "run", "-c", str(cfg))

        mock_build.assert_called_once()

    def test_agentic_run_does_not_write_anything_without_output_path(self):
        """
        `run` without -o must not write anything to disk by default (no
        implicit auto-save): only an explicit output path should ever cause
        a write.
        """
        cfg = _make_agentic_fixture(self.tmpdir)
        with patch("pathlib.Path.write_text") as mock_write_text:
            stdout, _, code = _run_cli("agentic", "run", "-c", str(cfg))

        mock_write_text.assert_not_called()
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertNotIn("_saved_to", data)
        self.assertNotIn("_save_error", data)

    def test_agentic_run_save_failure_with_explicit_output_does_not_discard_results(self):
        """
        Regression test: a disk-write failure when saving to an explicit -o
        path must not discard a result that already reflects completed,
        paid-for LLM calls. The CLI should still print the full JSON result
        (with a _save_error key) and exit 0, not crash with an uncaught
        PermissionError.
        """
        cfg = _make_agentic_fixture(self.tmpdir)
        out = Path(self.tmpdir) / "result.json"
        with patch(
            "pathlib.Path.write_text",
            side_effect=PermissionError("Permission denied: read-only filesystem"),
        ):
            stdout, _, code = _run_cli("agentic", "run", "-c", str(cfg), "-o", str(out))

        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertIn("profile", data)
        self.assertIn("token_usage", data)
        self.assertIn("_save_error", data)
        self.assertNotIn("_saved_to", data)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
