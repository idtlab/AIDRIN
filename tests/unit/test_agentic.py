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


if __name__ == "__main__":
    unittest.main()
