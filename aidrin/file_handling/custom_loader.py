"""Trusted custom data loaders: ``path/to/loader.py:function`` → DataFrame.

Used by CLI ``--loader``, library/batch ``loader``, and the web upload
``Other / custom loader`` option. Scripts run in-process via importlib; only use
trusted inputs.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class CustomLoaderError(ValueError):
    """Raised when a custom loader cannot be resolved or returns invalid data."""


_custom_loader_ctx: ContextVar[Optional[str]] = ContextVar(
    "aidrin_custom_loader", default=None
)


@contextmanager
def using_custom_loader(loader: Optional[str] = None) -> Iterator[None]:
    """Apply a ``path.py:function`` loader to all ``read_file`` calls in this context."""
    spec = (loader or "").strip() or None
    token = _custom_loader_ctx.set(spec)
    try:
        yield
    finally:
        _custom_loader_ctx.reset(token)


def get_custom_loader_spec() -> Optional[str]:
    return _custom_loader_ctx.get()


def parse_loader_spec(spec: str) -> Tuple[str, str]:
    """Parse ``module_or_file.py:function`` into ``(module_or_path, func_name)``."""
    if not spec or not isinstance(spec, str) or ":" not in spec:
        raise CustomLoaderError(
            "Custom loader spec must be in the form 'path/to/loader.py:function' "
            f"(got {spec!r})."
        )
    module_part, func_name = spec.rsplit(":", 1)
    module_part = module_part.strip()
    func_name = func_name.strip()
    if not module_part or not func_name:
        raise CustomLoaderError(
            "Custom loader spec must be in the form 'path/to/loader.py:function' "
            f"(got {spec!r})."
        )
    return module_part, func_name


def _format_loader_failure(spec: str, file_path: str, cause: str) -> str:
    return f"Custom loader '{spec}' failed for '{file_path}': {cause}"


def _resolve_callable(spec: str, file_path: str) -> Callable[..., Any]:
    module_part, func_name = parse_loader_spec(spec)
    path = Path(module_part)

    try:
        if path.suffix == ".py":
            candidates = [path]
            if not path.is_absolute():
                candidates.append(Path.cwd() / path)
            resolved = None
            for candidate in candidates:
                try:
                    cand = candidate.resolve()
                except OSError:
                    continue
                if cand.exists():
                    resolved = cand
                    break
            if resolved is None:
                raise CustomLoaderError(
                    _format_loader_failure(
                        spec,
                        file_path,
                        f"loader file not found: {module_part}",
                    )
                )
            mod_name = f"aidrin_custom_loader_{resolved.stem}_{id(resolved)}"
            mod_spec = importlib.util.spec_from_file_location(mod_name, str(resolved))
            if mod_spec is None or mod_spec.loader is None:
                raise CustomLoaderError(
                    _format_loader_failure(
                        spec,
                        file_path,
                        f"unable to load module from {resolved}",
                    )
                )
            module = importlib.util.module_from_spec(mod_spec)
            try:
                mod_spec.loader.exec_module(module)
            except Exception as exc:
                logger.error(
                    "Custom loader import failed for %s: %s", spec, exc, exc_info=True
                )
                raise CustomLoaderError(
                    _format_loader_failure(
                        spec,
                        file_path,
                        f"{type(exc).__name__}: {exc}",
                    )
                ) from exc
            func = getattr(module, func_name, None)
        else:
            try:
                module = importlib.import_module(module_part)
            except Exception as exc:
                logger.error(
                    "Custom loader import failed for %s: %s", spec, exc, exc_info=True
                )
                raise CustomLoaderError(
                    _format_loader_failure(
                        spec,
                        file_path,
                        f"{type(exc).__name__}: {exc}",
                    )
                ) from exc
            func = getattr(module, func_name, None)
    except CustomLoaderError:
        raise

    if not callable(func):
        raise CustomLoaderError(
            _format_loader_failure(
                spec,
                file_path,
                f"function '{func_name}' not found or not callable",
            )
        )
    return func


def load_dataframe(
    spec: str,
    file_path: str,
    **kwargs: Any,
) -> pd.DataFrame:
    """Load a DataFrame via a user loader.

    Parameters
    ----------
    spec:
        ``path/to/loader.py:function`` (or importable ``module:function``).
    file_path:
        Dataset path passed as the first positional argument to the loader.
    **kwargs:
        Forwarded to the loader (e.g. ``selected_keys``).
    """
    display_path = file_path or ""
    try:
        func = _resolve_callable(spec, display_path)
    except CustomLoaderError:
        raise
    except Exception as exc:
        logger.error("Custom loader resolve failed for %s: %s", spec, exc, exc_info=True)
        raise CustomLoaderError(
            _format_loader_failure(spec, display_path, f"{type(exc).__name__}: {exc}")
        ) from exc

    try:
        df = func(file_path, **kwargs)
    except CustomLoaderError:
        raise
    except Exception as exc:
        logger.error(
            "Custom loader %s raised for %s: %s", spec, display_path, exc, exc_info=True
        )
        raise CustomLoaderError(
            _format_loader_failure(
                spec,
                display_path,
                f"raised {type(exc).__name__}: {exc}",
            )
        ) from exc

    if df is None:
        raise CustomLoaderError(
            _format_loader_failure(
                spec,
                display_path,
                "returned None (expected pandas DataFrame)",
            )
        )
    if not isinstance(df, pd.DataFrame):
        raise CustomLoaderError(
            _format_loader_failure(
                spec,
                display_path,
                f"returned {type(df).__name__} (expected pandas DataFrame)",
            )
        )
    if df.empty:
        raise CustomLoaderError(
            _format_loader_failure(
                spec,
                display_path,
                "returned an empty DataFrame",
            )
        )
    return df


def get_active_loader_spec(explicit: Optional[str] = None) -> Optional[str]:
    """Return explicit loader, else headless context, else Flask session spec."""
    if explicit:
        return explicit
    ctx = get_custom_loader_spec()
    if ctx:
        return ctx
    try:
        from flask import has_request_context, session

        if has_request_context():
            spec = session.get("custom_loader_spec")
            if spec:
                return str(spec)
    except Exception:
        pass
    return None
