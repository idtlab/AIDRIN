import json

import pytest

from aidrin.file_handling.file_reference_policy import (
    allowed_roots,
    discovery_configuration,
    resolve_base_dir,
    scan_limit,
)


def test_explicit_policy_overrides_environment(monkeypatch, tmp_path):
    environment_root = tmp_path / "environment"
    explicit_root = tmp_path / "explicit"
    environment_root.mkdir()
    explicit_root.mkdir()
    monkeypatch.setenv("AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS", json.dumps([str(environment_root)]))
    monkeypatch.setenv("AIDRIN_FILE_REFERENCE_WEB_SCAN_LIMIT", "7")

    assert allowed_roots([str(explicit_root)]) == [str(explicit_root)]
    assert scan_limit(23) == 23


def test_environment_policy_is_fail_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS", raising=False)
    monkeypatch.setenv("AIDRIN_FILE_REFERENCE_WEB_SCAN_LIMIT", "invalid")

    config = discovery_configuration()

    assert config["enabled"] is False
    assert config["roots"] == []
    assert config["scan_limit"] == 10000


def test_resolve_base_dir_rejects_traversal_and_symlink_escape(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()

    with pytest.raises(ValueError, match="stay inside"):
        resolve_base_dir([str(root)], "root-0", "../outside")

    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are not supported")
    with pytest.raises(ValueError, match="stay inside"):
        resolve_base_dir([str(root)], "root-0", "link")


def test_resolve_base_dir_rejects_unknown_root(tmp_path):
    with pytest.raises(ValueError, match="Select an allowed"):
        resolve_base_dir([str(tmp_path)], "root-1", "")
