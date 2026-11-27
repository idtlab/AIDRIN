Register the AIDRIN local web OAuth app (maintainers)
====================================================

AIDRIN ships a **public native** Globus client ID in ``web/aidrin_globus_defaults.py``
so local users can click **Sign in with Globus** without setting environment variables.
Only the client ID is distributed; never commit a client secret.

1. Sign in at `Globus Developers <https://app.globus.org/settings/developers>`_.
2. Register a **Native App** (PKCE), e.g. name ``AIDRIN (local web)``.
3. Add these **Redirect URIs** (and any extra localhost ports your team uses):

   .. code-block:: text

      http://localhost:5000/globus/callback
      http://127.0.0.1:5000/globus/callback
      http://localhost:8080/globus/callback
      http://127.0.0.1:8080/globus/callback

4. Copy the assigned client UUID into ``AIDRIN_DEFAULT_GLOBUS_NATIVE_CLIENT_ID`` in
   ``web/aidrin_globus_defaults.py`` and update ``AIDRIN_LOCAL_WEB_OAUTH_REDIRECT_URIS``
   if you added more callbacks.

Hosted AIDRIN and other deployments should **not** rely on this bundled ID. Set
``GLOBUS_CLIENT_ID`` (and ``GLOBUS_CLIENT_SECRET`` for a confidential web client)
with redirect URIs for the deployment's public URL. Optionally set
``GLOBUS_REDIRECT_URI`` when the callback path differs from ``/globus/callback``.
