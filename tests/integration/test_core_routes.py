"""Tests for core routes: file operations, filter, retrieve."""

import re

import numpy as np
import pytest


# -------------------------------------------------
# Retrieve uploaded file
# -------------------------------------------------


def test_retrieve_file_without_upload(client):
    """Should return 404 when no file is uploaded."""
    response = client.get("/retrieve-uploaded-file")
    assert response.status_code == 404
    data = response.get_json()
    assert "error" in data


def test_retrieve_file_after_upload(uploaded_client):
    """Should return the uploaded file."""
    response = uploaded_client.get("/retrieve-uploaded-file")
    assert response.status_code == 200


# -------------------------------------------------
# Filter file (for hierarchical data)
# -------------------------------------------------


def test_filter_file_no_keys(client):
    """/filter-file without keys should return error."""
    response = client.post(
        "/filter-file",
        json={"keys": ""},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False


def test_filter_file_with_keys(uploaded_client):
    """/filter-file with keys should set session."""
    response = uploaded_client.post(
        "/filter-file",
        json={"keys": "age,income"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True


def test_filter_file_with_list_keys(uploaded_client):
    """/filter-file accepts keys as a list."""
    response = uploaded_client.post(
        "/filter-file",
        json={"keys": ["age", "income"]},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True


# -------------------------------------------------
# Summary statistics edge cases
# -------------------------------------------------


def test_summary_statistics_post_without_file(client):
    """POST to /summary-statistics without file should redirect."""
    response = client.post("/summary-statistics", follow_redirects=False)
    assert response.status_code == 302


def test_summary_statistics_get_without_file(client):
    """GET /summary-statistics without file should return error."""
    response = client.get("/summary-statistics")
    data = response.get_json()
    assert data["success"] is False


def _force_unreadable(client):
    """Mark the uploaded file as Parquet though its bytes are CSV, so read_file
    fails and returns an error string (reproduces the parquet-engine scenario)."""
    with client.session_transaction() as sess:
        sess["uploaded_file_type"] = ".parquet"


def test_summary_statistics_surfaces_read_error_gracefully(uploaded_client):
    """When the file cannot be read, the route returns a concise, friendly
    message, not a masked AttributeError or a raw exception dump."""
    _force_unreadable(uploaded_client)
    response = uploaded_client.get("/summary-statistics")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is False
    assert "AttributeError" not in data["message"]
    assert "could not be read" in data["message"].lower()
    assert len(data["message"]) < 160  # concise, not a wall of text


def test_extract_features_surfaces_read_error_gracefully(uploaded_client):
    """/feature-set should likewise surface a concise, friendly read error."""
    _force_unreadable(uploaded_client)
    response = uploaded_client.post("/feature-set")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is False
    assert "AttributeError" not in data["message"]
    assert "could not be read" in data["message"].lower()
    assert len(data["message"]) < 160


def test_load_dataframe_simplifies_parquet_engine_error(monkeypatch):
    """The verbose 'no usable engine' parquet error becomes a short message,
    while the full detail stays out of the user-facing string."""
    import web.routes.utils as utils

    verbose = (
        "Unable to find a usable engine; tried using: 'pyarrow', 'fastparquet'.\n"
        "A suitable version of pyarrow or fastparquet is required for parquet "
        "support.\nTrying to import the above resulted in these errors:\n"
        " - Missing optional dependency 'pyarrow'. ..."
    )
    monkeypatch.setattr(utils, "read_file", lambda file_info: verbose)
    df, message = utils.load_dataframe(("x.parquet", "x.parquet", ".parquet"))

    assert df is None
    assert "Trying to import" not in message
    assert "\n" not in message
    assert len(message) < 160
    assert "parquet" in message.lower()


def test_load_dataframe_simplifies_unknown_error(monkeypatch):
    """An unrecognised low-level error is replaced with a generic friendly
    message rather than leaked verbatim."""
    import web.routes.utils as utils

    monkeypatch.setattr(utils, "read_file", lambda file_info: "low-level kaboom 0xdeadbeef")
    df, message = utils.load_dataframe(("x.csv", "x.csv", ".csv"))

    assert df is None
    assert "kaboom" not in message
    assert "could not be read" in message.lower()


def test_load_dataframe_handles_reader_refusal(monkeypatch):
    """A reader that *raises* on an ambiguous input must not reach Flask.

    Formats in ``_RAISE_ON_EMPTY_FILE_TYPES`` (a multi-array Zarr store, and
    HDF5 once it joins them) raise instead of returning None, which would
    otherwise escape this wrapper and 500 the upload route.
    """
    import web.routes.utils as utils
    from aidrin.file_handling.file_parser import ReaderReturnedNone

    def _refuse(file_info):
        raise ReaderReturnedNone(
            "store 'x.zarr' has layout 'multi_dataset' and needs an explicit "
            "dataset selection."
        )

    monkeypatch.setattr(utils, "read_file", _refuse)
    df, message = utils.load_dataframe(("x.zarr", "x.zarr", ".zarr"))

    assert df is None
    assert message
    assert len(message) < 200


def test_load_dataframe_refusal_does_not_claim_corruption(monkeypatch):
    """An ambiguous layout is a readable file needing a choice, not a broken one."""
    import web.routes.utils as utils
    from aidrin.file_handling.file_parser import ReaderReturnedNone

    def _refuse(file_info):
        raise ReaderReturnedNone(
            "store 'x.zarr' has layout 'multi_dataset' and needs an explicit "
            "dataset selection."
        )

    monkeypatch.setattr(utils, "read_file", _refuse)
    _df, message = utils.load_dataframe(("x.zarr", "x.zarr", ".zarr"))

    assert "corrupted" not in message.lower()
    assert "select" in message.lower()


def test_load_dataframe_returns_df_for_valid_csv(sample_csv):
    """The shared helper returns a DataFrame and no error for a readable file."""
    import pandas as pd

    from web.routes.utils import load_dataframe

    df, err = load_dataframe((str(sample_csv), "test_data.csv", ".csv"))
    assert err is None
    assert isinstance(df, pd.DataFrame)


def test_load_dataframe_returns_message_on_read_error():
    """The shared helper converts a read failure into (None, message)."""
    from web.routes.utils import load_dataframe

    df, err = load_dataframe(("/nonexistent/file.csv", "file.csv", ".csv"))
    assert df is None
    assert err


# -------------------------------------------------
# Clear
# -------------------------------------------------


def test_clear_without_session(client):
    """/clear with empty session should still redirect."""
    response = client.post("/clear", follow_redirects=False)
    assert response.status_code == 302
    assert "/inspector" in response.headers["Location"]


# -------------------------------------------------
# Stale session: file type missing
# -------------------------------------------------


def test_stale_session_missing_type(client, sample_csv, app):
    """If file_type is missing from session, inspector should clear it."""
    # Upload a file
    with open(sample_csv, "rb") as f:
        client.post(
            "/inspector",
            data={"file": (f, "test.csv"), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    # Manually remove file_type from session
    with client.session_transaction() as sess:
        sess.pop("uploaded_file_type", None)

    # Inspector should detect stale session
    response = client.get("/inspector")
    html = response.data.decode()
    assert 'id="sidebar"' not in html


# -------------------------------------------------
# Sample data — every file the frontend advertises must actually exist
# -------------------------------------------------


def _sample_files_from_inspector_html(client):
    """Parse the `sampleFiles` JS array out of the rendered inspector page.

    Reads the list from the live template rather than duplicating it here,
    so this test catches a file being added to the frontend list (or
    renamed) without the corresponding file landing in examples/sample_data/.
    """
    html = client.get("/inspector").data.decode()
    match = re.search(r"const sampleFiles = \[(.*?)\];", html, re.DOTALL)
    assert match, "Could not find sampleFiles array in inspector.html"
    entries = re.findall(
        r"name:\s*'([^']+)',\s*type:\s*'([^']+)'", match.group(1)
    )
    assert entries, "sampleFiles array parsed but no entries found"
    return entries


def test_all_advertised_sample_files_are_downloadable(client):
    """Every file listed in the frontend's Sample Data panel must download
    successfully — a file listed there but missing on disk silently breaks
    the sample-data feature for that entry."""
    missing = []
    for name, file_type in _sample_files_from_inspector_html(client):
        response = client.get(f"/sample-data/{file_type}/{name}")
        if response.status_code != 200:
            missing.append((name, file_type, response.status_code))
    assert not missing, f"Sample files advertised but not downloadable: {missing}"


def _write_well_shaped_h5(path, grid=(1, 2, 8, 10)):
    """A gridded file in The Well's layout: scalar fields plus a vector field."""
    import h5py

    cells = int(np.prod(grid))
    with h5py.File(path, "w") as f:
        f.attrs["n_spatial_dims"] = 2
        f.create_dataset("dimensions/x", data=np.arange(grid[2], dtype="f4"))
        f.create_dataset("dimensions/y", data=np.arange(grid[3], dtype="f4"))
        f.create_dataset("t0_fields/density", data=np.arange(cells, dtype="f4").reshape(grid))
        f.create_dataset(
            "t0_fields/temperature", data=(np.arange(cells, dtype="f4") * 3).reshape(grid)
        )
        f.create_dataset(
            "t1_fields/velocity", data=np.arange(cells * 2, dtype="f4").reshape(grid + (2,))
        )


def _upload(client, path, name="well.h5"):
    with open(path, "rb") as handle:
        return client.post(
            "/inspector",
            data={"file": (handle, name), "fileTypeSelector": ".h5"},
            content_type="multipart/form-data",
        )


def test_filter_file_accepts_a_grid_selection(client, tmp_path):
    """The picker must accept what the reader can read.

    It kept its own copy of the rule, which rejected every grid selection as
    "not a 1D array" after the reader learned to flatten aligned grids.
    """
    pytest.importorskip("h5py")
    fpath = tmp_path / "well.h5"
    _write_well_shaped_h5(str(fpath))
    _upload(client, str(fpath))

    response = client.post(
        "/filter-file",
        json={"keys": ["t0_fields/density", "t0_fields/temperature", "t1_fields/velocity"]},
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_filter_file_rejects_fields_on_different_grids(client, tmp_path):
    pytest.importorskip("h5py")
    fpath = tmp_path / "well.h5"
    _write_well_shaped_h5(str(fpath))
    _upload(client, str(fpath))

    response = client.post(
        "/filter-file", json={"keys": ["t0_fields/density", "dimensions/x"]}
    )

    assert response.status_code == 400
    assert "grid" in response.get_json()["error"]


def test_summary_statistics_reports_grid_cells_as_rows(client, tmp_path):
    """End to end: a grid selection becomes one row per cell with split components."""
    pytest.importorskip("h5py")
    fpath = tmp_path / "well.h5"
    _write_well_shaped_h5(str(fpath))
    _upload(client, str(fpath))
    client.post(
        "/filter-file",
        json={"keys": ["t0_fields/density", "t1_fields/velocity"]},
    )

    payload = client.get("/summary-statistics").get_json()

    assert payload["success"] is True
    assert payload["records_count"] == 1 * 2 * 8 * 10
    assert payload["numerical_features"] == [
        "t0_fields/density",
        "t1_fields/velocity_0",
        "t1_fields/velocity_1",
    ]

