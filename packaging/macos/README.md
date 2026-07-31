# macOS app bundle

Builds a double-clickable `AIDRIN.app` that runs the Flask UI locally in a native window. No
Python install, no Redis, no terminal: Celery runs in eager mode so metrics execute in-process.

```bash
./packaging/macos/build.sh
```

Outputs `build/macos/dist/AIDRIN.app` and `build/macos/AIDRIN-<version>.dmg`.

The app icon is `packaging/macos/icon.png` (square; 1024x1024 is ideal, since macOS renders icons
up to that size). `build.sh` converts it to `.icns` and regenerates whenever the PNG is newer.
Without that file it falls back to `aidrin/images/logoNoBackground.png`. macOS applies its own
rounded-rect mask, so the source should be full-bleed rather than pre-rounded.

## How it works

`aidrin_app.py` is the bundle entry point. It sets `FLASK_CELERY__task_always_eager` (read by
`app.config.from_prefixed_env()` in `web/__init__.py`), picks a free localhost port, starts a
threaded Werkzeug server, and displays it in a pywebview (WKWebView) window. The localhost URL is
never visible to the user. Without pywebview installed the launcher falls back to the default
browser, which is what a source checkout does.

The bundle is read-only, so the launcher redirects every writable path to
`~/Library/Application Support/AIDRIN`:

| Variable | Contents |
| --- | --- |
| `AIDRIN_DATA_DIR` | uploads (`data/uploads`) and logs (`data/logs`) |
| `AIDRIN_CUSTOM_METRICS_DIR` | user-uploaded custom metric scripts and remedy output |
| `MPLCONFIGDIR`, `NUMBA_CACHE_DIR`, `XDG_CACHE_HOME` | third-party caches |

Those first two are read by `web/__init__.py` and `aidrin/logging.py`; unset, both keep their
original project-root defaults, so a source checkout behaves exactly as before.

Useful overrides when debugging: `AIDRIN_PORT` pins the port, `AIDRIN_NO_WINDOW=1` serves headless
(no window), `AIDRIN_NO_BROWSER=1` additionally skips opening a tab in that mode. Launcher output
goes to `~/Library/Application Support/AIDRIN/launcher.log`.

## Caveats

- **Unsigned.** The build is ad-hoc signed, which is enough to run on the machine that built it,
  but Gatekeeper will block it after download ("AIDRIN is damaged and can't be opened"). To
  distribute it, sign with a Developer ID certificate and notarize:
  ```bash
  codesign --force --deep --options runtime --sign "Developer ID Application: ..." AIDRIN.app
  xcrun notarytool submit AIDRIN-<version>.dmg --keychain-profile <profile> --wait
  xcrun stapler staple AIDRIN.app
  ```
  Without that, users must run `xattr -dr com.apple.quarantine /Applications/AIDRIN.app` once.
- **Architecture-specific.** The bundle matches the build machine (arm64 here). An Intel or
  universal build needs to be produced on/for that architecture.
- **Optional integrations are excluded** (Globus, OpenAI/LLM, agentic, OpenTelemetry). The
  `is_*_available()` probes report them as missing and their blueprints stay unregistered.
- **No `beat` scheduler.** The periodic cleanup tasks do not run in eager mode; `create_app()`
  still prunes aged uploads and custom metrics on every launch.
- **No in-window downloads.** WKWebView does not implement browser downloads, so any part of the
  UI that hands the user a file (the inspector's client-side export, remedy CSVs) will not save
  from the window. The app menu has an "Open in Browser" item as the escape hatch.
- **Quitting.** Closing the window quits the app; Cmd-Q and the Dock icon work because pywebview
  runs a real Cocoa app. `POST /__quit` does the same thing programmatically. Note that the
  Cocoa event loop owns the main thread, so Python signal handlers do not run promptly while the
  window is open — shutdown is driven directly rather than through `SIGTERM`.
