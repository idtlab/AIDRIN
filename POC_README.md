# PoC: AIDRIN Multiple File Formats

GSoC 2026 proof-of-concept for the AIDRIN Multiple File Formats project.

## What this PoC demonstrates

Two things:

**1. `zarrReader` — a new file format reader (`aidrin/file_handling/readers/zarr_reader.py`)**

Implements the `read() / parse() / filter()` contract defined by `BaseFileReader` and
already satisfied by all existing readers (CSV, HDF5, NPZ, etc.).  Registering it in
`READER_MAP` is the only change required to make the entire metric pipeline work with Zarr
stores — no changes to `main.py`, no changes to any metric code.

The interesting mechanism is `_collect_fill_values()`: Zarr arrays always carry a
`fill_value` in their metadata, but the default is `0`, which is ambiguous — it may be a
real measurement, not a missing-data marker.  The same explicit/uncertain split introduced
in `hdf5Reader` is applied here, so Zarr fill-value replacement produces the same
consistent NaN behaviour that HDF5 completeness metrics already rely on.

**2. `BaseIngestionPlugin` — a custom ingestion plugin ABC (`aidrin/custom_readers/base_ingestion_plugin.py`)**

A user subclasses `BaseIngestionPlugin`, implements `ingest(file_path) -> pd.DataFrame`,
uploads the file via a UI editor, and AIDRIN dynamically loads it with `importlib` —
exactly the same mechanism `BaseDRAgent` / `customMetrics` already uses on the output side.
No core code changes needed to support a new, unknown file format.

## Files added / changed

```
aidrin/
  file_handling/
    file_parser.py             ← zarr registered in READER_MAP + SUPPORTED_FILE_TYPES
    readers/
      zarr_reader.py           ← new: ZarrReader (read / parse / filter)
  custom_readers/
    __init__.py                ← new
    base_ingestion_plugin.py   ← new: BaseIngestionPlugin ABC

test_zarr_reader.py            ← new: 14 tests for zarrReader
test_custom_reader.py          ← new: 10 tests for BaseIngestionPlugin + dynamic loading
pyproject.toml                 ← zarr>=2.16,<3.0 added to dependencies
```

## How to run locally

### 1. Install the extra dependency

```bash
pip install "zarr>=2.16,<3.0"
```

All other dependencies are already in `pyproject.toml`.

### 2. Install the package in editable mode (if not already)

```bash
pip install -e .
```

### 3. Run the PoC tests

```bash
pytest test_zarr_reader.py test_custom_reader.py -v
```

Expected output: **24 passed**.

### 4. Quick smoke test from a Python REPL

```python
import logging, numpy as np, zarr
from aidrin.file_handling.readers.zarr_reader import zarrReader

# Create a tiny in-memory-backed store
store = zarr.open_group("smoke.zarr", mode="w")
store.create_dataset("temperature", data=np.array([20.1, -9999.0, 22.3, 21.8]))

log = logging.getLogger("smoke")
df = zarrReader("smoke.zarr", log, fill_values=[-9999.0]).read()
print(df)
# completeness
print("completeness:", 1 - df.isnull().mean().mean())
```

```python
# Custom plugin (no file format support needed in core code)
import pandas as pd
from aidrin.custom_readers.base_ingestion_plugin import BaseIngestionPlugin

class TsvReader(BaseIngestionPlugin):
    def ingest(self, file_path: str) -> pd.DataFrame:
        return pd.read_csv(file_path, sep="\t")

plugin = TsvReader()
# plugin.ingest("my_data.tsv") → DataFrame ready for AIDRIN metrics
```
