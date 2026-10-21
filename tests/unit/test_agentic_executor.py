"""Unit tests for aidrin.agentic.executor.CodeExecutor.

Covers the process-based execution/timeout behavior: a timed-out attempt
must actually be killed, not merely abandoned, so it can never perform a
side effect or overlap with a subsequent repair attempt. See _execute's
docstring for why this runs in a subprocess rather than a thread.
"""

from __future__ import annotations

import os
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

try:
    import langchain_openai  # noqa: F401
    HAS_AGENTIC_DEPS = True
except ImportError:
    HAS_AGENTIC_DEPS = False

import pandas as pd

# CodeExecutor eagerly constructs a chat model client when executor.enabled
# is true, which needs *some* key string present to construct (even though
# none of the tests below ever call .invoke() — no repair is needed since
# max_attempts=1). This environment has no real key or litellm installed, so
# a placeholder avoids an ImportError/missing-credentials error at construction.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder-not-a-real-key")


def _write_config(tmpdir: str, data_path: Path, timeout_seconds: float, max_attempts: int = 1) -> Path:
    cfg_path = Path(tmpdir) / "config.yaml"
    cfg_path.write_text(
        textwrap.dedent(f"""\
            executor:
              enabled: true
              max_attempts: {max_attempts}
              timeout_seconds: {timeout_seconds}
            paths:
              data_csv: {data_path}
        """),
        encoding="utf-8",
    )
    return cfg_path


@unittest.skipUnless(HAS_AGENTIC_DEPS, "agentic extras not installed (pip install 'aidrin[agentic]')")
class TestCodeExecutorSubprocess(unittest.TestCase):
    def setUp(self):
        from aidrin.agentic.executor import CodeExecutor

        self.CodeExecutor = CodeExecutor
        self.tmpdir = tempfile.mkdtemp()
        self.data_path = Path(self.tmpdir) / "data.csv"
        self.data_path.write_text("x\n1\n2\n3\n", encoding="utf-8")
        self.df = pd.read_csv(self.data_path)
        # _execute() takes a path to a pickled dataframe (read fresh by each
        # attempt's child process), not the dataframe itself -- see
        # _run_code_in_subprocess's docstring for why.
        self.df_path = Path(self.tmpdir) / "df.pkl"
        self.df.to_pickle(self.df_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_success_path_returns_answer_via_subprocess(self):
        # A generous timeout: spawning a process and reimporting the package
        # costs real wall-clock time before any code runs (see _execute's
        # docstring), so this isn't testing timeout behavior.
        cfg = _write_config(self.tmpdir, self.data_path, timeout_seconds=15)
        executor = self.CodeExecutor(cfg)
        result = executor._execute("result = int(df['x'].sum())", self.df_path)
        self.assertEqual(result["answer"], 6)

    def test_error_in_code_raises_runtime_error_with_message(self):
        cfg = _write_config(self.tmpdir, self.data_path, timeout_seconds=15)
        executor = self.CodeExecutor(cfg)
        with self.assertRaises(RuntimeError) as ctx:
            executor._execute("raise ValueError('boom')", self.df_path)
        self.assertIn("boom", str(ctx.exception))

    def test_timeout_seconds_is_floored(self):
        from aidrin.agentic.executor import _MIN_TIMEOUT_SECONDS

        cfg = _write_config(self.tmpdir, self.data_path, timeout_seconds=0)
        executor = self.CodeExecutor(cfg)
        self.assertEqual(executor.timeout_seconds, _MIN_TIMEOUT_SECONDS)

    def test_timeout_raises(self):
        # Configured above _MIN_TIMEOUT_SECONDS (5.0) so the floor doesn't
        # change what's actually being tested here.
        cfg = _write_config(self.tmpdir, self.data_path, timeout_seconds=6)
        executor = self.CodeExecutor(cfg)
        with self.assertRaises(TimeoutError) as ctx:
            executor._execute("import time\ntime.sleep(10)\nresult = 1", self.df_path)
        self.assertIn("timeout", str(ctx.exception).lower())

    def test_timeout_actually_kills_the_process_not_just_abandons_it(self):
        """
        Regression test: a prior thread-based implementation could only
        abandon a hung attempt on timeout (Python has no safe way to kill a
        thread), so the abandoned thread kept running and could still
        perform side effects, or overlap with a subsequent repair attempt,
        after _execute had already raised TimeoutError and moved on.

        This proves the replacement (a child process, terminated and joined
        before _execute returns) actually stops the code: a side effect
        scheduled to happen *after* the timeout elapses must never be
        observed, even after waiting well past when it would have run.
        """
        marker = Path(self.tmpdir) / "side_effect_marker.txt"
        # Configured above _MIN_TIMEOUT_SECONDS (5.0) so the floor doesn't
        # change what's actually being tested here.
        cfg = _write_config(self.tmpdir, self.data_path, timeout_seconds=6)
        executor = self.CodeExecutor(cfg)

        slow_code = f"""
import time
time.sleep(10)
with open({str(marker)!r}, "w") as f:
    f.write("ran")
"""
        start = time.time()
        with self.assertRaises(TimeoutError):
            executor._execute(slow_code, self.df_path)
        elapsed = time.time() - start

        # Returns around the 6s timeout (plus spawn/terminate overhead),
        # not after waiting out the full 10s sleep.
        self.assertLess(elapsed, 9)

        # Wait past when the sleep(10) would have completed if the process
        # were merely abandoned rather than killed.
        time.sleep(6)
        self.assertFalse(marker.exists(), "side effect ran after timeout: the process was not actually killed")

    def test_large_result_does_not_deadlock_or_misreport_as_timeout(self):
        """
        Regression test: multiprocessing.Queue.put() hands off to a background
        feeder thread that blocks if the OS pipe buffer (~64KB) fills with
        nobody draining it. A prior implementation called process.join(timeout)
        before ever reading the queue, so a fast attempt whose result exceeded
        that size looked "still alive" at the deadline, got killed, and was
        misreported as a timeout — even though it had already finished
        computing. The fix drains the queue while waiting, not after.
        """
        cfg = _write_config(self.tmpdir, self.data_path, timeout_seconds=10)
        executor = self.CodeExecutor(cfg)
        # A couple MB, comfortably past the ~64KB pipe buffer, computed
        # near-instantly (no sleep) so a correct implementation returns in
        # well under the 10s timeout.
        code = "result = 'x' * 2_000_000"
        result = executor._execute(code, self.df_path)
        self.assertEqual(result["answer"], "x" * 2_000_000)

    def test_run_reports_timeout_as_last_error_without_crashing(self):
        cfg = _write_config(self.tmpdir, self.data_path, timeout_seconds=6, max_attempts=1)
        executor = self.CodeExecutor(cfg)
        result = executor.run(
            retrieval_result={"code": "import time\ntime.sleep(10)\nresult = 1", "query": "slow"}
        )
        self.assertFalse(result["success"])
        self.assertIn("timeout", result["last_error"].lower())


if __name__ == "__main__":
    unittest.main()
