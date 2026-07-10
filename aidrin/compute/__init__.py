"""Remote-execution helpers for AIDRIN (Globus Compute).

These functions are defined in the ``aidrin`` package so they are importable on
a remote compute endpoint, which has ``aidrin`` installed but not the ``web``
Flask application.
"""

from aidrin.compute.remote import remote_metric_runner, remote_env_probe

__all__ = ["remote_metric_runner", "remote_env_probe"]
