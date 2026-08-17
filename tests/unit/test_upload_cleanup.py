"""Unit tests for the scheduled upload-folder reaper in ``worker.tasks``.

Exercises the pure ``prune_upload_folder`` helper (no Flask/Celery/Redis): it
removes uploaded sources *and* their ``.aidrin.feather`` cache sidecars once they
age past the threshold, so long-running servers don't accumulate them.
"""

import os
import shutil
import tempfile
import unittest

from worker.tasks import prune_upload_folder


class PruneUploadFolderTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _make(self, name, age_seconds, now):
        path = os.path.join(self.dir, name)
        with open(path, "w") as fh:
            fh.write("x")
        mtime = now - age_seconds
        os.utime(path, (mtime, mtime))
        return path

    def test_removes_old_source_and_sidecar_keeps_fresh(self):
        now = 1_000_000.0
        old_src = self._make("u1.csv", age_seconds=7200, now=now)
        old_cache = self._make("u1.csv.123-456.aidrin.feather", age_seconds=7200, now=now)
        fresh_src = self._make("u2.csv", age_seconds=10, now=now)
        fresh_cache = self._make("u2.csv.9-9.aidrin.feather", age_seconds=10, now=now)

        removed = prune_upload_folder(self.dir, max_age_seconds=3600, now=now)

        self.assertFalse(os.path.exists(old_src))
        self.assertFalse(os.path.exists(old_cache))
        self.assertTrue(os.path.exists(fresh_src))
        self.assertTrue(os.path.exists(fresh_cache))
        self.assertEqual(removed, 2)

    def test_missing_folder_is_noop(self):
        removed = prune_upload_folder(
            os.path.join(self.dir, "does-not-exist"), max_age_seconds=3600, now=1.0
        )
        self.assertEqual(removed, 0)

    def test_ignores_subdirectories(self):
        now = 1_000_000.0
        sub = os.path.join(self.dir, "keep_dir")
        os.mkdir(sub)
        os.utime(sub, (now - 7200, now - 7200))
        removed = prune_upload_folder(self.dir, max_age_seconds=3600, now=now)
        self.assertTrue(os.path.isdir(sub))
        self.assertEqual(removed, 0)


if __name__ == "__main__":
    unittest.main()
