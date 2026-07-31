"""Unit tests for endpoint profile storage and resolution."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aidrin.compute import profiles


class _ProfileTestCase(unittest.TestCase):
    """Redirects both config locations into temp dirs for every test."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.project = tempfile.mkdtemp()
        self._env = patch.dict(
            os.environ, {"AIDRIN_CONFIG_DIR": self.home}, clear=False
        )
        self._env.start()
        os.environ.pop("AIDRIN_GLOBUS_ENDPOINT", None)
        self._cwd = patch.object(Path, "cwd", staticmethod(lambda: Path(self.project)))
        self._cwd.start()

    def tearDown(self):
        self._cwd.stop()
        self._env.stop()


class TestSaveAndList(_ProfileTestCase):

    def test_save_creates_user_config(self):
        path = profiles.save_profile("nersc", "uuid-1", default=True, aidrin_version="0.9.2")
        self.assertEqual(path, Path(self.home) / "config.json")
        data = json.loads(path.read_text())
        self.assertEqual(data["default"], "nersc")
        self.assertEqual(data["profiles"]["nersc"]["endpoint"], "uuid-1")
        self.assertEqual(data["profiles"]["nersc"]["aidrin_version"], "0.9.2")

    def test_config_file_is_owner_only(self):
        path = profiles.save_profile("nersc", "uuid-1")
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_first_profile_becomes_default_without_flag(self):
        profiles.save_profile("nersc", "uuid-1")
        self.assertEqual(profiles.list_profiles()["default"], "nersc")

    def test_second_profile_does_not_steal_default(self):
        profiles.save_profile("nersc", "uuid-1")
        profiles.save_profile("alcf", "uuid-2")
        self.assertEqual(profiles.list_profiles()["default"], "nersc")

    def test_local_writes_project_file(self):
        path = profiles.save_profile("lab", "uuid-3", local=True)
        self.assertEqual(path, Path(self.project) / ".aidrin.json")

    def test_list_merges_project_over_user(self):
        profiles.save_profile("nersc", "user-uuid")
        profiles.save_profile("nersc", "project-uuid", local=True)
        merged = profiles.list_profiles()
        self.assertEqual(merged["profiles"]["nersc"]["endpoint"], "project-uuid")


class TestRemove(_ProfileTestCase):

    def test_remove_returns_true_and_deletes(self):
        profiles.save_profile("nersc", "uuid-1")
        self.assertTrue(profiles.remove_profile("nersc"))
        self.assertNotIn("nersc", profiles.list_profiles()["profiles"])

    def test_remove_missing_returns_false(self):
        self.assertFalse(profiles.remove_profile("ghost"))

    def test_removing_default_clears_default(self):
        profiles.save_profile("nersc", "uuid-1", default=True)
        profiles.remove_profile("nersc")
        self.assertIsNone(profiles.list_profiles()["default"])


class TestResolve(_ProfileTestCase):

    def test_explicit_endpoint_wins(self):
        profiles.save_profile("nersc", "uuid-1", default=True)
        os.environ["AIDRIN_GLOBUS_ENDPOINT"] = "env-uuid"
        target = profiles.resolve(endpoint="flag-uuid", profile="nersc")
        self.assertEqual(target.endpoint, "flag-uuid")
        self.assertEqual(target.source, "flag")

    def test_named_profile_beats_env(self):
        profiles.save_profile("nersc", "uuid-1")
        os.environ["AIDRIN_GLOBUS_ENDPOINT"] = "env-uuid"
        target = profiles.resolve(profile="nersc")
        self.assertEqual(target.endpoint, "uuid-1")
        self.assertEqual(target.source, "profile")

    def test_env_beats_stored_default(self):
        profiles.save_profile("nersc", "uuid-1", default=True)
        os.environ["AIDRIN_GLOBUS_ENDPOINT"] = "env-uuid"
        target = profiles.resolve()
        self.assertEqual(target.endpoint, "env-uuid")
        self.assertEqual(target.source, "env")

    def test_falls_back_to_default_profile(self):
        profiles.save_profile("nersc", "uuid-1", default=True, aidrin_version="0.9.1")
        target = profiles.resolve()
        self.assertEqual(target.endpoint, "uuid-1")
        self.assertEqual(target.profile, "nersc")
        self.assertEqual(target.aidrin_version, "0.9.1")

    def test_unknown_profile_raises(self):
        with self.assertRaises(profiles.ProfileError) as ctx:
            profiles.resolve(profile="ghost")
        self.assertIn("ghost", str(ctx.exception))

    def test_nothing_configured_raises_with_guidance(self):
        with self.assertRaises(profiles.ProfileError) as ctx:
            profiles.resolve()
        message = str(ctx.exception)
        self.assertIn("aidrin remote configure", message)
        self.assertIn("AIDRIN_GLOBUS_ENDPOINT", message)

    def test_project_default_wins_and_reports_source_project(self):
        profiles.save_profile("nersc", "user-uuid", default=True)
        profiles.save_profile("lab", "project-uuid", default=True, local=True)
        target = profiles.resolve()
        self.assertEqual(target.endpoint, "project-uuid")
        self.assertEqual(target.profile, "lab")
        self.assertEqual(target.source, "project")

    def test_user_default_reports_source_user(self):
        profiles.save_profile("nersc", "user-uuid", default=True)
        target = profiles.resolve()
        self.assertEqual(target.endpoint, "user-uuid")
        self.assertEqual(target.profile, "nersc")
        self.assertEqual(target.source, "user")

    def test_dangling_project_default_falls_through_to_user_default(self):
        profiles.save_profile("nersc", "user-uuid", default=True)
        # Hand-edited project file: its default names a profile that isn't
        # defined anywhere (not even in this same file).
        project_path = profiles.project_config_path()
        project_path.write_text(json.dumps({"default": "ghost", "profiles": {}}))
        target = profiles.resolve()
        self.assertEqual(target.endpoint, "user-uuid")
        self.assertEqual(target.profile, "nersc")
        self.assertEqual(target.source, "user")


class TestWritePermissions(_ProfileTestCase):

    def test_write_corrects_preexisting_wide_permissions(self):
        # If the config file already exists at a wider mode (e.g. created
        # before this module enforced 0600, or by another tool), saving a
        # profile must still leave it at 0600 -- the create path used to
        # write the full content before chmod-ing, which is what this
        # guards against.
        path = profiles.user_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"default": None, "profiles": {}}))
        os.chmod(path, 0o644)
        profiles.save_profile("nersc", "uuid-1")
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o600)
