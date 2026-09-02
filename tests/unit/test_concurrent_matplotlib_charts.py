"""Concurrent pyplot chart generation must not cross-contaminate outputs.

Matplotlib's pyplot API is process-global and not thread-safe (see AGENTS.md).
Several metric/visualization helpers still call ``plt.savefig`` / ``plt.title`` on
the implicit current figure. Under threaded request handling those calls interleave.

These tests:

1. Require production chart helpers to serialize behind ``MATPLOTLIB_PLOT_LOCK``
   (fails until the lock is wired into ``web/routes/utils.py`` chart builders).
2. Demonstrate that the same global-pyplot pattern races without a lock, and is
   stable when the lock is held (passes only after the lock symbol exists).
"""

from __future__ import annotations

import concurrent.futures
import io
import re
import time
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
import pandas as pd

UTILS_PATH = Path(__file__).resolve().parents[2] / "web" / "routes" / "utils.py"


def _racey_global_pyplot_chart(marker: int) -> bytes:
    """Mirrors the unsafe ``plt.figure`` / ``plt.savefig`` pattern used in some metrics."""
    plt.figure(figsize=(1.2, 1.2), dpi=40)
    # Stretch the critical section so concurrent threads reliably interleave.
    time.sleep(0.015)
    xs = np.linspace(0, 1, 20)
    plt.plot(xs, np.full_like(xs, float(marker)), linewidth=4)
    plt.title(f"marker-{marker}")
    plt.ylim(-1, 256)
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    return buf.getvalue()


class TestMatplotlibPlotLockContract(unittest.TestCase):
    def test_utils_chart_helpers_use_shared_plot_lock(self):
        source = UTILS_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "MATPLOTLIB_PLOT_LOCK",
            source,
            "Define a process-wide threading.Lock as MATPLOTLIB_PLOT_LOCK in "
            "web/routes/utils.py and wrap chart generation with it.",
        )
        self.assertRegex(
            source,
            r"with\s+MATPLOTLIB_PLOT_LOCK\s*:",
            "summary_histograms / categorical_distribution_charts must enter "
            "MATPLOTLIB_PLOT_LOCK around pyplot figure work.",
        )
        for fn in ("def summary_histograms", "def categorical_distribution_charts"):
            self.assertIn(fn, source)
            # Lock acquisition must appear after each function definition and
            # before the next top-level def (rough structural check).
            start = source.index(fn)
            nxt = re.search(r"\n\ndef ", source[start + 1 :])
            body = source[start : start + 1 + (nxt.start() if nxt else len(source))]
            self.assertIn(
                "MATPLOTLIB_PLOT_LOCK",
                body,
                f"{fn} must hold MATPLOTLIB_PLOT_LOCK for the duration of plotting.",
            )


class TestConcurrentGlobalPyplot(unittest.TestCase):
    def test_lock_prevents_global_pyplot_cross_contamination(self):
        try:
            from web.routes.utils import MATPLOTLIB_PLOT_LOCK
        except ImportError as exc:
            self.fail(
                "MATPLOTLIB_PLOT_LOCK is missing; add it in web/routes/utils.py "
                f"before chart helpers. Import error: {exc}"
            )

        markers = [10, 200]

        def locked(marker: int) -> bytes:
            with MATPLOTLIB_PLOT_LOCK:
                return _racey_global_pyplot_chart(marker)

        baseline = {m: locked(m) for m in markers}
        self.assertNotEqual(baseline[10], baseline[200])

        mismatches = 0
        workers = 8
        waves = 10
        for _ in range(waves):
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                jobs = [
                    pool.submit(locked, markers[i % 2]) for i in range(workers * 2)
                ]
                for i, job in enumerate(jobs):
                    got = job.result()
                    expected = baseline[markers[i % 2]]
                    if got != expected:
                        mismatches += 1

        self.assertEqual(
            mismatches,
            0,
            f"{mismatches} locked concurrent chart(s) still diverged from baseline.",
        )

    def test_unlocked_global_pyplot_is_racy(self):
        """Control: without a lock, concurrent global-pyplot charts diverge.

        Skipped once the production lock exists *and* this machine happens not
        to race — we only require that unlocked runs can detect contamination
        when the lock symbol is still absent (pre-fix) or when forced.
        """
        try:
            from web.routes.utils import MATPLOTLIB_PLOT_LOCK  # noqa: F401
            has_lock = True
        except ImportError:
            has_lock = False

        markers = [10, 200]
        baseline = {m: _racey_global_pyplot_chart(m) for m in markers}
        mismatches = 0
        workers = 8
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = [
                pool.submit(_racey_global_pyplot_chart, markers[i % 2])
                for i in range(workers * 3)
            ]
            for i, job in enumerate(jobs):
                got = job.result()
                expected = baseline[markers[i % 2]]
                if got != expected:
                    mismatches += 1

        if not has_lock:
            self.assertGreater(
                mismatches,
                0,
                "Expected unlocked concurrent pyplot charts to cross-contaminate; "
                "increase sleep in _racey_global_pyplot_chart if this is flaky.",
            )
        # After the fix, unlocked races may still happen; this control is informational.
        # The contract + locked tests are the gate.


if __name__ == "__main__":
    unittest.main()
