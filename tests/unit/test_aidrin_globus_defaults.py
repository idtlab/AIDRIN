"""Bundled AIDRIN Globus native client defaults (issue #206)."""

import re
import uuid

from web.aidrin_globus_defaults import (
    AIDRIN_DEFAULT_GLOBUS_NATIVE_CLIENT_ID,
    AIDRIN_LOCAL_WEB_OAUTH_REDIRECT_URIS,
    aidrin_bundled_globus_native_client_id,
)


def test_bundled_client_id_is_uuid():
    client_id = aidrin_bundled_globus_native_client_id()
    assert client_id == AIDRIN_DEFAULT_GLOBUS_NATIVE_CLIENT_ID.strip()
    uuid.UUID(client_id)


def test_local_redirect_uri_list_covers_default_flask_port():
    assert any("localhost:5000/globus/callback" in uri for uri in AIDRIN_LOCAL_WEB_OAUTH_REDIRECT_URIS)
    for uri in AIDRIN_LOCAL_WEB_OAUTH_REDIRECT_URIS:
        assert re.match(r"^https?://", uri)
