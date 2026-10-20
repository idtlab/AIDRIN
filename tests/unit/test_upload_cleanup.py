"""Unit tests for the scheduled upload-folder reaper in ``worker.tasks``.

Exercises the pure ``prune_upload_folder`` helper (no Flask/Celery/Redis): it
removes uploaded sources *and* their ``.aidrin.feather`` cache sidecars once they
age past the threshold, so long-running servers don't accumulate them.
"""

import os
import shutil
import tempfile
import unittest

from worker.tasks import prune_upload_folder, prune_custom_metrics_folder


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


class PruneCustomMetricsFolderTestCase(unittest.TestCase):
    """CUSTOM_METRICS_FOLDER holds both permanent package source
    (__init__.py, base_dr.py, template.py) and session-generated scripts
    (customDR_<uuid>.py). Only the latter should ever be pruned — a prior
    version used an exclude-list of "known good" filenames instead of
    matching the generated-file pattern, and it silently deleted
    template.py because nobody had added it to the list."""

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

    def test_prunes_stale_generated_scripts_only(self):
        now = 1_000_000.0
        old_generated = self._make("customDR_11111111-1111-1111-1111-111111111111.py", 7200, now)
        fresh_generated = self._make("customDR_22222222-2222-2222-2222-222222222222.py", 10, now)
        old_init = self._make("__init__.py", 7200, now)
        old_base_dr = self._make("base_dr.py", 7200, now)
        old_template = self._make("template.py", 7200, now)

        removed = prune_custom_metrics_folder(self.dir, max_age_seconds=3600, now=now)

        self.assertFalse(os.path.exists(old_generated))
        self.assertTrue(os.path.exists(fresh_generated))
        self.assertTrue(os.path.exists(old_init))
        self.assertTrue(os.path.exists(old_base_dr))
        self.assertTrue(os.path.exists(old_template))
        self.assertEqual(removed, 1)

    def test_missing_folder_is_noop(self):
        removed = prune_custom_metrics_folder(
            os.path.join(self.dir, "does-not-exist"), max_age_seconds=3600, now=1.0
        )
        self.assertEqual(removed, 0)


class DeleteOldUploadsTaskTestCase(unittest.TestCase):
    """Web custom loader scripts live outside UPLOAD_FOLDER, so the scheduled
    reaper must prune CUSTOM_LOADERS_FOLDER too or abandoned sessions leave
    user-supplied code behind indefinitely."""

    def setUp(self):
        self.uploads = tempfile.mkdtemp()
        self.loaders = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.uploads, ignore_errors=True)
        shutil.rmtree(self.loaders, ignore_errors=True)

    def test_prunes_aged_custom_loader_scripts(self):
        import time

        from flask import Flask

        from worker.tasks import delete_old_uploads

        cache = os.path.join(self.loaders, "__pycache__")
        os.makedirs(cache)
        old_loader = os.path.join(self.loaders, f"custom_loader_{'a' * 32}.py")
        old_bytecode = os.path.join(cache, f"custom_loader_{'a' * 32}.cpython-312.pyc")
        fresh_loader = os.path.join(self.loaders, f"custom_loader_{'b' * 32}.py")
        unrelated = os.path.join(self.loaders, "notes.txt")
        aged = time.time() - 7200
        for path in (old_loader, old_bytecode, fresh_loader, unrelated):
            with open(path, "w") as fh:
                fh.write("def load(path): ...")
        for path in (old_loader, old_bytecode, unrelated):
            os.utime(path, (aged, aged))

        app = Flask(__name__)
        app.config.update(UPLOAD_FOLDER=self.uploads, CUSTOM_LOADERS_FOLDER=self.loaders)
        with app.app_context():
            # .run() skips the Celery task wrapper, which would push the web app's
            # context (and folders) once create_app() has run elsewhere in the suite.
            delete_old_uploads.run()

        self.assertFalse(os.path.exists(old_loader))
        self.assertFalse(os.path.exists(old_bytecode))
        self.assertTrue(os.path.exists(fresh_loader))
        self.assertTrue(os.path.exists(unrelated))
