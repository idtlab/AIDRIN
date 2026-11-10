"""The local compose stack must share the upload folder across containers.

``web`` saves uploads to ``UPLOAD_FOLDER`` and hands Celery tasks the *path*
(see ``web.routes.utils.build_file_info``). ``worker`` reads that path back.
Split across containers without a shared mount, the worker looks at its own
empty copy of the directory and every path-based metric (feature relevance,
correlation analysis, conditional demographic disparity) fails with
"Failed to read the file". The ``delete_old_uploads`` beat task prunes the
wrong directory for the same reason.
"""

import os
import unittest

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMPOSE_FILE = os.path.join(REPO_ROOT, "docker", "local", "docker-compose.yml")

# Mirrors ``web.create_app``: ``<project_root>/data/uploads`` with the repo
# copied to /app in docker/local/Dockerfile.
UPLOAD_PATH_IN_CONTAINER = "/app/data/uploads"

# Every service that touches UPLOAD_FOLDER: web writes, worker reads, beat prunes.
SERVICES_NEEDING_UPLOADS = ("web", "worker", "beat")


def _upload_mount_source(service):
    """Return the volume source mounted at the upload path, or None."""
    for mount in service.get("volumes", []):
        if isinstance(mount, str):
            parts = mount.split(":")
            if len(parts) >= 2 and parts[1] == UPLOAD_PATH_IN_CONTAINER:
                return parts[0]
        elif isinstance(mount, dict) and mount.get("target") == UPLOAD_PATH_IN_CONTAINER:
            return mount.get("source")
    return None


class TestLocalComposeSharesUploads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(COMPOSE_FILE, encoding="utf-8") as handle:
            # PyYAML resolves the `<<: *aidrin-app` merge keys, so each service
            # here is its effective configuration.
            cls.compose = yaml.safe_load(handle)
        cls.services = cls.compose["services"]

    def test_every_app_service_mounts_the_upload_folder(self):
        for name in SERVICES_NEEDING_UPLOADS:
            with self.subTest(service=name):
                self.assertIsNotNone(
                    _upload_mount_source(self.services[name]),
                    f"service {name!r} has no volume mounted at {UPLOAD_PATH_IN_CONTAINER}",
                )

    def test_the_upload_mount_is_the_same_volume_everywhere(self):
        sources = {
            name: _upload_mount_source(self.services[name])
            for name in SERVICES_NEEDING_UPLOADS
        }
        self.assertEqual(
            len(set(sources.values())),
            1,
            f"services must share one upload volume, got {sources}",
        )

    def test_the_shared_upload_volume_is_declared(self):
        source = _upload_mount_source(self.services["web"])
        # Bind mounts (./path, /abs) need no declaration; named volumes do.
        if source and not source.startswith((".", "/", "~")):
            self.assertIn(
                source,
                self.compose.get("volumes") or {},
                f"named volume {source!r} is used but not declared under top-level `volumes`",
            )


if __name__ == "__main__":
    unittest.main()
