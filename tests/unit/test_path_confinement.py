"""Tests for the upload-folder path-traversal barrier.

Web-supplied dataset paths (from the Flask session) flow into ``file_parser``'s
filesystem calls. ``confine_to_upload_folder`` is the barrier that keeps those
paths inside ``UPLOAD_FOLDER`` (CWE-22 / CodeQL ``py/path-injection``).
"""

import os
import shutil
import tempfile
import unittest

from flask import Flask

from web.routes.utils import build_file_info, confine_to_upload_folder


class ConfineToUploadFolderTests(unittest.TestCase):
    def setUp(self):
        self.upload_dir = tempfile.mkdtemp()
        self.app = Flask(__name__)
        self.app.config["UPLOAD_FOLDER"] = self.upload_dir
        self.app.secret_key = "test-secret"
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()
        shutil.rmtree(self.upload_dir, ignore_errors=True)

    def test_accepts_path_inside_upload_folder(self):
        inside = os.path.join(self.upload_dir, "abc123_data.csv")
        self.assertEqual(confine_to_upload_folder(inside), os.path.realpath(inside))

    def test_rejects_parent_traversal(self):
        escape = os.path.join(self.upload_dir, "..", "..", "etc", "passwd")
        self.assertEqual(confine_to_upload_folder(escape), "")

    def test_rejects_absolute_outside_path(self):
        self.assertEqual(confine_to_upload_folder("/etc/passwd"), "")

    def test_missing_path_returns_empty(self):
        self.assertEqual(confine_to_upload_folder(""), "")
        self.assertEqual(confine_to_upload_folder(None), "")

    def test_build_file_info_nulls_out_escaping_path(self):
        info = build_file_info("/etc/passwd", "passwd", ".csv")
        self.assertEqual(info[0], "")

    def test_build_file_info_keeps_valid_path(self):
        inside = os.path.join(self.upload_dir, "abc123_data.csv")
        info = build_file_info(inside, "data.csv", ".csv")
        self.assertEqual(info[0], os.path.realpath(inside))

    def test_build_file_info_embeds_custom_loader_for_celery(self):
        inside = os.path.join(self.upload_dir, "sample.root")
        with self.app.test_request_context():
            from flask import session

            session["custom_loader_spec"] = r"C:\tmp\loader.py:load"
            info = build_file_info(inside, "sample.root", ".root")
        self.assertEqual(info[0], os.path.realpath(inside))
        self.assertEqual(info[2], ".root")
        self.assertEqual(info[3], r"C:\tmp\loader.py:load")


if __name__ == "__main__":
    unittest.main()
