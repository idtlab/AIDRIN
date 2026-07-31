"""Executes headless AIDRIN calls on a remote Globus Compute endpoint.

``RemoteExecutor`` is duck-typed against the ``aidrin.headless.api`` *module*:
it exposes the same four function names with the same signatures (parameter
names and order), so callers substitute one for the other and never branch on
local versus remote.

Two defaults are intentionally different from the ``api`` module, because a
remote submission has constraints a local call does not: ``save_images``
defaults to off (``api`` defaults it on) since the endpoint must never write
files, and ``strip_visualizations`` resolves via the image policy below
(``True`` unless images were requested) rather than a fixed default, since
Globus Compute caps a task result near 10 MB and visualization payloads are
base64 PNGs.
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
        file_name: Optional[str] = None,
        save_images: bool = False,
        image_dir: Optional[str] = None,
        verbose: bool = False,
        strip_visualizations: Optional[bool] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Same parameter order as ``api.run_metric`` so positional calls work.

        ``save_images`` defaults to ``False`` here (``api`` defaults to
        ``True``) and ``strip_visualizations`` defaults to ``None``, a sentinel
        meaning "let the image policy decide" rather than ``api``'s fixed
        ``False`` -- see the module docstring.
        """
        image_kwargs: Dict[str, Any] = {"save_images": save_images, "image_dir": image_dir}
        if strip_visualizations is not None:
            image_kwargs["strip_visualizations"] = strip_visualizations
        want_images, image_dir = self._image_policy(image_kwargs)
        payload = {
            "metric_name": metric_name,
            "file_path": file_path,
            "file_type": file_type,
            "file_name": file_name,
            "verbose": verbose,
        }
        payload.update(image_kwargs)
        payload.update(kwargs)
        result = self._call("run_metric", payload)
        return _maybe_save_images(metric_name, result, want_images, image_dir)

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
        strip_visualizations: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Same image policy as ``run_metric``, applied to the batch config.

        ``HeadlessConfig``/dict carries its own ``save_images``/``image_dir``,
        so those (not a method parameter) are what "the caller wants images"
        is read from. ``strip_visualizations`` defaults to ``None`` here (a
        sentinel meaning "let the image policy decide"), unlike ``api``'s
        fixed ``False`` default, for the same reason as ``run_metric``.
        """
        # run_batch_metrics accepts a dict, so the endpoint never needs the
        # config file itself. Paths inside it must be endpoint-visible.
        payload_config = asdict(config) if is_dataclass(config) else dict(config)
        image_kwargs: Dict[str, Any] = {
            "save_images": payload_config.get("save_images"),
            "image_dir": payload_config.get("image_dir"),
        }
        if strip_visualizations is not None:
            image_kwargs["strip_visualizations"] = strip_visualizations
        want_images, image_dir = self._image_policy(image_kwargs)
        payload_config["save_images"] = image_kwargs["save_images"]
        result = self._call(
            "batch",
            {
                "config": payload_config,
                "verbose": verbose,
                "strip_visualizations": image_kwargs["strip_visualizations"],
            },
        )
        if not want_images:
            return result
        return {
            metric_name: _maybe_save_images(metric_name, metric_result, True, image_dir)
            for metric_name, metric_result in result.items()
        }
