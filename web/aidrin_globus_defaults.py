"""Bundled Globus OAuth defaults for AIDRIN local web sign-in (issue #206).

@idtlab/aidrin maintainers register a **public native** Globus application (PKCE;
no client secret in this repository) and set ``AIDRIN_DEFAULT_GLOBUS_NATIVE_CLIENT_ID``
below. See ``examples/globus/web-oauth-local-app.rst`` for redirect URIs to register.

Hosted and other self-hosted deployments override this with ``GLOBUS_CLIENT_ID``
(and optionally ``GLOBUS_CLIENT_SECRET`` for a confidential client).
"""

# Public native client ID for local ``localhost`` / ``127.0.0.1`` web sign-in.
# @idtlab/aidrin: register "AIDRIN (local web)" at Globus Developers and paste
# the assigned UUID here (see examples/globus/web-oauth-local-app.rst).
# Until that app exists, this interim ID matches the historical bundled default
# used for local PKCE testing; replace it with the AIDRIN-owned registration.
AIDRIN_DEFAULT_GLOBUS_NATIVE_CLIENT_ID = "4cf29807-cf21-49ec-9443-ff9a3fb9f81c"

# Redirect URIs to add when registering the AIDRIN-owned native app (common dev ports).
AIDRIN_LOCAL_WEB_OAUTH_REDIRECT_URIS = (
    "http://localhost:5000/globus/callback",
    "http://127.0.0.1:5000/globus/callback",
    "http://localhost:8080/globus/callback",
    "http://127.0.0.1:8080/globus/callback",
)


def aidrin_bundled_globus_native_client_id():
    """Return the bundled public native client ID, or empty if unset."""
    return (AIDRIN_DEFAULT_GLOBUS_NATIVE_CLIENT_ID or "").strip()
