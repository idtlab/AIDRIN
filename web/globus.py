"""Optional Globus Compute integration for AIDRIN.

When ``globus-compute-sdk`` is installed (``pip install aidrin[globus]``),
this module provides remote metric execution via Globus Compute endpoints.
When the packages are **not** installed, ``is_globus_available()`` returns
False and all other functions raise ImportError — the inspector hides the
Globus UI entirely.
"""

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

_globus_available = False

try:
    from globus_compute_sdk import Client as ComputeClient
    from globus_sdk import (
        ConfidentialAppAuthClient,
        NativeAppAuthClient,
        AccessTokenAuthorizer,
    )
    _globus_available = True
except ImportError:
    pass


def is_globus_available():
    """Return True if the Globus Compute SDK is installed."""
    return _globus_available


# ---------------------------------------------------------------------------
# The function that runs on the remote endpoint
# ---------------------------------------------------------------------------

def remote_metric_runner(metric_name, file_path, file_name, file_type, **params):
    """Execute an AIDRIN metric on the remote Globus Compute endpoint.

    This function is serialised and sent to the remote endpoint, where it
    imports ``aidrin`` locally and dispatches to the requested metric.
    The remote environment must have ``pip install aidrin`` completed.
    """
    # Ensure matplotlib uses non-interactive backend on remote endpoint
    import matplotlib
    matplotlib.use("Agg")

    import aidrin

    file_info = (file_path, file_name, file_type)

    def _data_quality():
        """Run selected data quality sub-metrics and bundle results."""
        result = {}
        selected = params.get("selected", ["completeness", "outliers", "duplicates"])
        if "completeness" in selected:
            r = aidrin.calculate_completeness(file_info)
            r["Description"] = (
                "Indicate the proportion of available data for each feature, "
                "with values closer to 1 indicating high completeness, and values near "
                "0 indicating low completeness."
            )
            result["Completeness"] = r
        if "outliers" in selected:
            r = aidrin.calculate_outliers(file_info)
            r["Description"] = (
                "Outlier scores are calculated for numerical columns using the IQR method, "
                "where a score of 1 indicates all data points are outliers, "
                "and 0 signifies no outliers."
            )
            result["Outliers"] = r
        if "duplicates" in selected:
            r = aidrin.calculate_duplicates(file_info)
            r["Description"] = (
                "A value of 0 indicates no duplicates, and a value closer to 1 signifies "
                "a higher proportion of duplicated data points."
            )
            result["Duplicity"] = r
        return result

    def _summary_statistics():
        """Compute summary statistics + histograms on the remote file."""
        import io
        import base64
        import pandas as pd
        import matplotlib.pyplot as plt
        import seaborn as sns
        from aidrin.file_handling.file_parser import read_file as _read_file

        df = _read_file(file_info)
        if isinstance(df, str):
            return {"error": df}

        numerical_columns = [
            col for col, dtype in df.dtypes.items() if pd.api.types.is_numeric_dtype(dtype)
        ]
        categorical_columns = [
            col for col, dtype in df.dtypes.items() if pd.api.types.is_string_dtype(dtype)
        ]
        all_features = numerical_columns + categorical_columns

        summary = df.describe().map(
            lambda x: round(x, 2) if x == 0 or abs(x) >= 0.001 else f"{x:.2e}"
        ).to_dict()

        # Rename percentile keys
        for v in summary.values():
            for old_key in list(v.keys()):
                if old_key in ["25%", "50%", "75%"]:
                    v[old_key.replace("%", "th percentile")] = v.pop(old_key)

        # Generate histograms (transparent, same as local)
        text_color = "#6b7280"
        curve_color = "#4485F4"
        histograms = {}
        for column in df.select_dtypes(include="number").columns:
            try:
                fig, ax = plt.subplots(figsize=(4, 3))
                fig.patch.set_alpha(0)
                ax.set_facecolor("none")
                sns.kdeplot(df[column], bw_adjust=0.5, ax=ax, color=curve_color)
                ax.set_xlabel("Values", fontsize=10, color=text_color)
                ax.set_ylabel("Density", fontsize=10, color=text_color)
                ax.tick_params(colors=text_color, labelsize=8)
                for spine in ax.spines.values():
                    spine.set_color(text_color)
                fig.tight_layout(pad=0.5)
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=150, transparent=True)
                buf.seek(0)
                histograms[f"{column}_light"] = base64.b64encode(buf.read()).decode("utf-8")
                plt.close(fig)
                buf.close()
            except Exception:
                pass

        return {
            "success": True,
            "records_count": len(df),
            "features_count": len(df.columns),
            "categorical_features": list(categorical_columns),
            "numerical_features": list(numerical_columns),
            "all_features": all_features,
            "summary_statistics": summary,
            "histograms": histograms,
            "class_imbalance_features": [
                col for col in all_features if df[col].nunique() <= 30
            ],
        }

    def _fairness():
        """Run selected fairness sub-metrics and bundle results (matching local route)."""
        from aidrin.structured_data_metrics.representation_rate import (
            calculate_representation_rate as _calc_rr,
            create_representation_rate_vis as _vis_rr,
        )
        aidrin._eager_celery()
        result = {}
        selected = params.get("selected", [])

        if "representation_rate" in selected:
            columns = params.get("rep_columns", [])
            rep_dict = {}
            rep_dict["Probability ratios"] = _calc_rr.apply(args=(columns, file_info)).get()
            rep_dict["Representation Rate Visualization"] = _vis_rr.apply(args=(columns, file_info)).get()
            rep_dict["Description"] = (
                "Probability ratios quantify the relative representation of different "
                "categories within the sensitive features, highlighting differences in "
                "representation rates between various groups."
            )
            result["Representation Rate"] = rep_dict

        if "statistical_rates" in selected:
            sr_dict = aidrin.calculate_statistical_rates(
                params.get("sensitive_attr", ""),
                params.get("y_true", ""),
                file_info,
            )
            sr_dict["Description"] = (
                "The graph illustrates the statistical rates of various classes across "
                "different sensitive attributes."
            )
            result["Statistical Rate"] = sr_dict

        return result

    dispatch = {
        "summary_statistics": _summary_statistics,
        "data_quality": _data_quality,
        "completeness": lambda: aidrin.calculate_completeness(file_info),
        "outliers": lambda: aidrin.calculate_outliers(file_info),
        "duplicates": lambda: aidrin.calculate_duplicates(file_info),
        "correlations": lambda: aidrin.calculate_correlations(
            params.get("columns", []), file_info
        ),
        "feature_relevance": lambda: aidrin.calculate_feature_relevance(
            file_info,
            params["target_col"],
            params.get("cat_cols"),
            params.get("num_cols"),
        ),
        "fairness": _fairness,
        "representation_rate": _fairness,  # alias — routes through _fairness
        "statistical_rates": _fairness,    # alias
        "k_anonymity": lambda: aidrin.compute_k_anonymity(
            params.get("quasi_ids", []), file_info
        ),
        "l_diversity": lambda: aidrin.compute_l_diversity(
            params.get("quasi_ids", []),
            params["sensitive_col"],
            file_info,
        ),
        "t_closeness": lambda: aidrin.compute_t_closeness(
            params.get("quasi_ids", []),
            params["sensitive_col"],
            file_info,
        ),
        "entropy_risk": lambda: aidrin.compute_entropy_risk(
            params.get("quasi_ids", []), file_info
        ),
        "class_distribution": lambda: aidrin.calculate_class_distribution(
            params["column"], file_info
        ),
    }

    fn = dispatch.get(metric_name)
    if fn is None:
        return {"error": f"Unknown metric: {metric_name}"}

    try:
        result = fn()
        # Ensure all values are JSON-serializable (convert numpy types, etc.)
        import json
        try:
            json.dumps(result)
        except (TypeError, ValueError):
            # Fall back to recursive conversion
            def _make_serializable(obj):
                import numpy as np
                import pandas as pd
                if isinstance(obj, dict):
                    return {str(k): _make_serializable(v) for k, v in obj.items()}
                elif isinstance(obj, (list, tuple)):
                    return [_make_serializable(i) for i in obj]
                elif isinstance(obj, (np.integer,)):
                    return int(obj)
                elif isinstance(obj, (np.floating,)):
                    return float(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                elif isinstance(obj, (np.bool_,)):
                    return bool(obj)
                elif isinstance(obj, pd.Timestamp):
                    return obj.isoformat()
                elif isinstance(obj, set):
                    return list(obj)
                return obj
            result = _make_serializable(result)
        return result
    except Exception as e:
        return {"error": f"Remote execution failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

GLOBUS_COMPUTE_SCOPE = (
    "https://auth.globus.org/scopes/facd7ccc-c5f4-42aa-916b-a0e270e2c2a9/all"
)
GLOBUS_AUTH_SCOPE = "openid profile email"


def _get_client_id():
    client_id = os.environ.get("GLOBUS_CLIENT_ID")
    if not client_id:
        raise ValueError(
            "GLOBUS_CLIENT_ID environment variable is required. "
            "Register an app at https://developers.globus.org/"
        )
    return client_id


def _get_client_secret():
    return os.environ.get("GLOBUS_CLIENT_SECRET")


GLOBUS_SCOPES = [GLOBUS_COMPUTE_SCOPE, GLOBUS_AUTH_SCOPE]

# Store auth client in memory between redirect and callback.
# Keyed by a random state string stored in the user's session.
_pending_auth_clients = {}


def get_auth_url(redirect_uri):
    """Generate the Globus Auth login URL for the OAuth2 redirect flow.

    Returns (auth_url, state_key) — the URL to redirect the user to,
    and a state key to retrieve the auth client in the callback.
    """
    if not _globus_available:
        raise ImportError("globus-sdk is not installed")

    import uuid
    client_id = _get_client_id()
    client_secret = _get_client_secret()

    # Use ConfidentialAppAuthClient if secret is provided (web app),
    # otherwise fall back to NativeAppAuthClient (console/dev)
    if client_secret:
        auth_client = ConfidentialAppAuthClient(
            client_id=client_id, client_secret=client_secret
        )
    else:
        auth_client = NativeAppAuthClient(client_id=client_id)

    auth_client.oauth2_start_flow(
        redirect_uri=redirect_uri,
        requested_scopes=GLOBUS_SCOPES,
    )
    auth_url = auth_client.oauth2_get_authorize_url()

    # Keep the auth client alive in server memory for the callback
    state_key = uuid.uuid4().hex
    _pending_auth_clients[state_key] = auth_client

    return auth_url, state_key


def exchange_code_for_tokens(auth_code, state_key):
    """Exchange the OAuth2 authorization code for access tokens.

    Uses the same auth client instance that generated the original auth URL
    (preserves the PKCE verifier).

    Returns a dict of tokens keyed by resource server.
    """
    auth_client = _pending_auth_clients.pop(state_key, None)
    if auth_client is None:
        raise ValueError("Auth session expired or invalid. Please try again.")

    logger.info(
        "Token exchange: client_type=%s, client_id=%s, has_secret=%s",
        type(auth_client).__name__,
        auth_client.client_id,
        bool(_get_client_secret()),
    )

    try:
        token_response = auth_client.oauth2_exchange_code_for_tokens(auth_code)
    except Exception as e:
        logger.error("Token exchange failed: %s", e, exc_info=True)
        raise

    return token_response.by_resource_server


# ---------------------------------------------------------------------------
# Globus Compute client
# ---------------------------------------------------------------------------

_function_uuid_cache = {}  # Cleared on every server restart → always re-registers latest code


def get_compute_client(tokens):
    """Create a Globus Compute client from stored tokens.

    Parameters
    ----------
    tokens : dict
        Token dict from ``exchange_code_for_tokens()``, stored in Flask session.
    """
    if not _globus_available:
        raise ImportError("globus-compute-sdk is not installed")

    # Token resource server key varies by SDK version
    compute_tokens = None
    for key in ("funcx_service", "compute.api.globus.org", "groups.api.globus.org"):
        if key in tokens and "access_token" in tokens[key]:
            compute_tokens = tokens[key]
            break

    if compute_tokens is None:
        # Try all keys and find one with an access_token
        for key, val in tokens.items():
            if isinstance(val, dict) and "access_token" in val:
                compute_tokens = val
                logger.info("Using token from resource server: %s", key)
                break

    if compute_tokens is None:
        available_keys = list(tokens.keys())
        raise ValueError(f"No Globus Compute access token found. Available: {available_keys}")

    access_token = compute_tokens["access_token"]

    try:
        return ComputeClient(
            authorizer=AccessTokenAuthorizer(access_token),
        )
    except TypeError:
        # Newer SDK versions may use different constructor
        return ComputeClient()


def register_function(client, force=False):
    """Register the remote_metric_runner function with Globus Compute.

    Returns the function UUID. Re-registers on every server restart
    to ensure the latest code is used.
    """
    cache_key = "remote_metric_runner"
    if not force and cache_key in _function_uuid_cache:
        return _function_uuid_cache[cache_key]

    func_uuid = client.register_function(remote_metric_runner)
    _function_uuid_cache[cache_key] = func_uuid
    logger.info("Registered remote_metric_runner with Globus Compute: %s", func_uuid)
    return func_uuid


# ---------------------------------------------------------------------------
# Task submission and status
# ---------------------------------------------------------------------------


def submit_metric(client, endpoint_id, metric_name, file_path, file_name, file_type, **params):
    """Submit a metric computation task to a remote Globus Compute endpoint.

    Returns the task UUID string for polling.
    """
    func_uuid = register_function(client)

    # Pass all arguments as positional args to avoid kwarg conflicts
    # with endpoint_id/function_id. The remote_metric_runner signature is:
    # remote_metric_runner(metric_name, file_path, file_name, file_type, **params)
    task_id = client.run(
        metric_name, file_path, file_name, file_type,
        endpoint_id=endpoint_id,
        function_id=func_uuid,
        # Pass params as a single keyword arg that remote_metric_runner unpacks
        **{k: v for k, v in params.items() if k not in ('endpoint_id', 'function_id')},
    )

    logger.info(
        "Submitted Globus Compute task %s: metric=%s endpoint=%s file=%s func=%s params=%s",
        task_id, metric_name, endpoint_id, file_path, func_uuid, params,
    )
    return str(task_id)


def check_task(client, task_id):
    """Check the status of a Globus Compute task.

    Returns a dict matching the format used by the inspector's pollAsyncMetric:
    ``{"status": "processing|completed|failed", "result": ..., "error": ...}``
    """
    try:
        result = client.get_result(task_id)
        # get_result returns the result directly if complete,
        # raises Exception if pending or failed
        return {"status": "completed", "result": result}
    except Exception as e:
        error_str = str(e)
        if "pending" in error_str.lower() or "waiting" in error_str.lower():
            return {"status": "processing", "progress": {"status": "Running on remote endpoint..."}}
        return {"status": "failed", "error": error_str}
