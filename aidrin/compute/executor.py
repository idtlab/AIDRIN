"""Executes headless AIDRIN calls on a remote Globus Compute endpoint.

``RemoteExecutor`` is duck-typed against the ``aidrin.headless.api`` *module*:
it exposes the same four function names with the same signatures, so callers
substitute one for the other and never branch on local versus remote.
"""

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional

from aidrin.compute import client
from aidrin.compute.profiles import RemoteTarget
from aidrin.headless.api import _maybe_save_images


class AsyncSubmitted(Exception):
    """Raised in detached mode instead of returning a result.

    Control flow, not failure: the caller catches this, prints the task id, and
    exits 0. Using an exception keeps every call site free of a detach branch.
    """

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(task_id)


class RemoteExecutor:
    """Runs headless commands on ``target.endpoint``."""

    def __init__(
        self,
        target: RemoteTarget,
        *,
        timeout: float = client.DEFAULT_TIMEOUT,
        detach: bool = False,
        compute_client: Any = None,
    ):
        self.target = target
        self.timeout = timeout
        self.detach = detach
        self._client = compute_client

    # -- internals ---------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            self._client = client.get_client()
        return self._client

    def _call(self, command: str, kwargs: Dict[str, Any]) -> Any:
        conn = self._get_client()
        task_id = client.submit(conn, self.target.endpoint, command, kwargs)
        if self.detach:
            raise AsyncSubmitted(task_id)
        return client.poll(conn, task_id, timeout=self.timeout)

    @staticmethod
    def _image_policy(kwargs: Dict[str, Any]) -> tuple:
        """Split image handling into what the endpoint does and what we do.

        The endpoint never writes files. When the caller wants images we ask for
        the visualization payloads to survive the trip, then write them here.
        """
        save_images = bool(kwargs.pop("save_images", False))
        image_dir = kwargs.pop("image_dir", None)
        kwargs["save_images"] = False
        if save_images:
            kwargs["strip_visualizations"] = False
        else:
            kwargs.setdefault("strip_visualizations", True)
        return save_images, image_dir

    # -- api-compatible surface -------------------------------------------

    def run_metric(
        self,
        metric_name: str,
        file_path: str,
        file_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        save_images, image_dir = self._image_policy(kwargs)
        payload = {"metric_name": metric_name, "file_path": file_path, "file_type": file_type}
        payload.update(kwargs)
        result = self._call("run_metric", payload)
        return _maybe_save_images(metric_name, result, save_images, image_dir)

    def summarize_dataset(
        self,
        file_path: str,
        file_type: Optional[str] = None,
        max_features: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._call(
            "summarize",
            {"file_path": file_path, "file_type": file_type, "max_features": max_features},
        )

    def run_data_quality(
        self,
        file_path: str,
        file_type: Optional[str] = None,
        file_name: Optional[str] = None,
        verbose: bool = False,
        strip_visualizations: bool = True,
    ) -> Dict[str, Any]:
        return self._call(
            "data_quality",
            {
                "file_path": file_path,
                "file_type": file_type,
                "file_name": file_name,
                "verbose": verbose,
                "strip_visualizations": strip_visualizations,
            },
        )

    def run_batch_metrics(
        self,
        config: Any,
        verbose: bool = False,
        strip_visualizations: bool = False,
    ) -> Dict[str, Any]:
        # run_batch_metrics accepts a dict, so the endpoint never needs the
        # config file itself. Paths inside it must be endpoint-visible.
        payload = asdict(config) if is_dataclass(config) else dict(config)
        return self._call(
            "batch",
            {
                "config": payload,
                "verbose": verbose,
                "strip_visualizations": strip_visualizations,
            },
        )
