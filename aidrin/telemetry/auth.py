"""Authenticate to an MLflow server that sits behind an API gateway.

MLflow's own ``MLFLOW_TRACKING_TOKEN`` only ever emits ``Authorization: Bearer``.
Gateways commonly want the credential in a header of their own — Kong's key-auth
plugin uses ``apikey`` or ``x-api-key``, for instance — which that cannot
express, so those deployments reject every request with a 401 that says nothing
about the cause.

MLflow's supported extension point for this is ``RequestHeaderProvider``. Set
both of:

* ``AIDRIN_MLFLOW_AUTH_HEADER`` — the header name, e.g. ``x-api-key``
* ``AIDRIN_MLFLOW_AUTH_KEY`` — the credential

and every MLflow request carries it. Unset, this is inert: MLflow's normal
authentication (token, basic auth, mTLS) is untouched.
"""

import logging
import os

logger = logging.getLogger(__name__)

HEADER_ENV = "AIDRIN_MLFLOW_AUTH_HEADER"
KEY_ENV = "AIDRIN_MLFLOW_AUTH_KEY"

_registered = False


def _base_class():
    from mlflow.tracking.request_header.abstract_request_header_provider import (
        RequestHeaderProvider,
    )

    return RequestHeaderProvider


try:  # pragma: no cover - exercised whenever the mlflow extra is installed
    class ApiKeyHeaderProvider(_base_class()):
        """Adds ``{AIDRIN_MLFLOW_AUTH_HEADER: AIDRIN_MLFLOW_AUTH_KEY}`` to requests."""

        def in_context(self):
            return bool(
                os.environ.get(HEADER_ENV, "").strip()
                and os.environ.get(KEY_ENV, "").strip()
            )

        def request_headers(self):
            return {os.environ[HEADER_ENV].strip(): os.environ[KEY_ENV].strip()}

except Exception:  # pragma: no cover - mlflow not installed
    ApiKeyHeaderProvider = None


def register():
    """Register the provider with MLflow, once per process.

    Called from the sink when tracking is enabled, so a user only has to set the
    two environment variables.
    """
    global _registered

    if _registered or ApiKeyHeaderProvider is None:
        return
    if not os.environ.get(HEADER_ENV, "").strip():
        return

    try:
        from mlflow.tracking.request_header.registry import (
            _request_header_provider_registry,
        )

        _request_header_provider_registry.register(ApiKeyHeaderProvider)
        _registered = True
        logger.info(
            "MLflow: sending credentials in the %s header",
            os.environ[HEADER_ENV].strip(),
        )
    except Exception as exc:
        logger.warning(
            "MLflow: could not register the %s auth header (%s)",
            HEADER_ENV,
            type(exc).__name__,
        )
