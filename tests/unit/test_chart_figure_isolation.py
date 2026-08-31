"""Charts must draw on their own figure, not matplotlib's global current figure.

The readiness report builds charts in the request thread, so any metric that
draws via the pyplot state machine (``plt.bar``/``plt.title``/``plt.savefig``)
can have its figure captured or mutated by a concurrent request. These tests
exercise the real chart functions rather than a stand-in, so reintroducing a
global-pyplot call fails them.
"""

import base64
import hashlib
import io
import threading

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from aidrin.structured_data_metrics.add_noise import return_noisy_stats  # noqa: E402
from aidrin.structured_data_metrics.class_imbalance import (  # noqa: E402
    class_distribution_plot,
)
from aidrin.structured_data_metrics.privacy_measure import (  # noqa: E402
    compute_entropy_risk,
    compute_k_anonymity,
    compute_l_diversity,
    compute_t_closeness,
)


def _qi_frame(seed, rows=200):
    rng = np.random.RandomState(seed)
    spread = 2 if seed else 25
    return pd.DataFrame(
        {
            "zip": rng.randint(0, spread, rows).astype(str),
            "age": rng.randint(0, spread, rows).astype(str),
            "sens": rng.choice(list("xyz"), rows),
        }
    )


def _digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


CHART_CASES = {
    "k_anonymity": (
        lambda s: compute_k_anonymity(["zip", "age"], _qi_frame(s)),
        "k-Anonymity Visualization",
    ),
    "l_diversity": (
        lambda s: compute_l_diversity(["zip"], "sens", _qi_frame(s)),
        "l-Diversity Visualization",
    ),
    "t_closeness": (
        lambda s: compute_t_closeness(["zip"], "sens", _qi_frame(s)),
        "t-Closeness Visualization",
    ),
    "entropy_risk": (
        lambda s: compute_entropy_risk(["zip"], _qi_frame(s)),
        "Entropy Risk Visualization",
    ),
}


@pytest.mark.parametrize("name", sorted(CHART_CASES))
def test_chart_is_unaffected_by_a_concurrent_chart(name):
    """A chart built while other charts render must match the serial baseline.

    Drawing on the global current figure makes one thread's savefig capture
    another thread's axes, so this fails if that style is reintroduced.
    """
    build, key = CHART_CASES[name]

    def render(seed):
        return _digest(build(seed).get(key, ""))

    baseline = {seed: render(seed) for seed in (0, 1)}
    # Serial control: identical input must give identical bytes, otherwise a
    # concurrent difference would prove nothing.
    for seed in (0, 1):
        assert render(seed) == baseline[seed], "chart output is not deterministic"

    mismatches = []

    def worker(index):
        seed = index % 2
        if render(seed) != baseline[seed]:
            mismatches.append(index)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not mismatches, (
        f"{name} chart was corrupted by concurrent rendering in "
        f"{len(mismatches)} of {len(threads)} threads"
    )


def test_charts_do_not_leak_figures():
    """Every chart closes its own figure, including when the metric fails."""
    frame = pd.DataFrame({"v": np.random.RandomState(0).normal(size=120)})
    plt.close("all")
    for _ in range(3):
        compute_k_anonymity(["zip", "age"], _qi_frame(0))
        class_distribution_plot(_qi_frame(0), "zip")
        return_noisy_stats(["v"], 0.5, frame, False)
        with pytest.raises(Exception):
            return_noisy_stats(["missing"], 0.5, frame, False)
    assert plt.get_fignums() == [], (
        f"chart functions leaked {len(plt.get_fignums())} open figures"
    )


def test_chart_png_is_a_real_image():
    """Guards against a chart silently becoming empty or malformed."""
    encoded = compute_k_anonymity(["zip", "age"], _qi_frame(0))[
        "k-Anonymity Visualization"
    ]
    raw = base64.b64decode(encoded)
    assert raw.startswith(b"\x89PNG\r\n\x1a\n"), "chart is not a PNG"
    assert len(raw) > 5000, "chart PNG is suspiciously small"
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as img:
        assert img.size[0] > 200 and img.size[1] > 200
