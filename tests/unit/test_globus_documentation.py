from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_local_provider_example_sets_worker_policy():
    config = yaml.safe_load(
        (REPO_ROOT / "examples" / "globus" / "aidrin-local-provider.yaml").read_text()
    )

    provider = config["engine"]["provider"]
    assert provider["type"] == "LocalProvider"
    assert "source /opt/aidrin/.venv/bin/activate" in provider["worker_init"]
    assert "AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS" in provider["worker_init"]
    assert "AIDRIN_FILE_REFERENCE_WEB_SCAN_LIMIT=10000" in provider["worker_init"]


def test_globus_docs_cover_worker_and_interface_boundaries():
    contributing = (REPO_ROOT / "docs" / "source" / "contributing.rst").read_text()
    usage = (REPO_ROOT / "docs" / "source" / "web_usage.rst").read_text()

    assert "worker_init" in contributing
    assert "Scheduler-backed providers" in contributing
    assert "container_cmd_options" in contributing
    assert "Globus Connect and Globus Transfer are not part" in contributing
    assert "``aidrin remote`` commands" in contributing
    assert "MCP calls that pass ``endpoint`` or ``profile``" in contributing
    assert "Globus Compute worker" in usage
    assert "MCP calls" in usage
    assert "with ``endpoint`` or ``profile`` check the selected Compute endpoint" in usage
