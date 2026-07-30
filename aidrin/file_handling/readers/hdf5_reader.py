import os
import uuid

import h5py
import numpy as np
import pandas as pd
from flask import current_app, session

from aidrin.file_handling.readers.base_reader import BaseFileReader


class hdf5Reader(BaseFileReader):
    def __init__(self, file_path: str, logger, fill_values=None, selected_keys=None):
        super().__init__(file_path, logger)
        # Optional user-supplied fill values merged with auto-detected ones.
        # Accepts any iterable of scalars, e.g. fill_values=[-9999, -1].
        self.fill_values = set(fill_values) if fill_values is not None else set()
        # Explicit keys for Celery workers (no Flask session). None = use session.
        self._explicit_selected_keys = selected_keys

    def _collect_fill_values(self, dataset):
        """Return (explicit, uncertain) sets of numeric missing-data sentinels.

        explicit — safe to replace silently:
            • User-supplied values passed at construction time.
            • ``_FillValue`` attribute (NetCDF/CF convention).
            • ``missing_value`` attribute (older NetCDF convention; may be a
              scalar or a 1-D array of multiple sentinels).
            • The HDF5 native ``dataset.fillvalue`` when it is non-zero *or*
              when fill-value attributes are present (the producer clearly
              cared about missingness, so the native value is intentional).

        uncertain — producer intent is ambiguous, warn before replacing:
            • The HDF5 native ``dataset.fillvalue`` when it equals the dtype
              default (0 / 0.0) *and* no fill-value attributes are present.
              HDF5 always stores a fill value; without an explicit assignment
              it defaults to zero, which is a valid measurement in counts,
              indices, and many physical quantities.

        Only numeric values are collected; non-numeric sentinels are skipped
        because the dtype guard in read() excludes string/compound datasets
        before this method is called.
        """
        explicit = set(self.fill_values)

        for attr_name in ("_FillValue", "missing_value"):
            if attr_name in dataset.attrs:
                raw = dataset.attrs[attr_name]
                for v in np.atleast_1d(raw).ravel():
                    try:
                        explicit.add(float(v))
                    except (TypeError, ValueError):
                        pass

        uncertain = set()
        try:
            native = float(dataset.fillvalue)
            if native not in explicit:
                dtype_default = float(np.zeros(1, dtype=dataset.dtype)[0])
                if native == dtype_default:
                    # Native fill equals the dtype default (0 / 0.0).  HDF5
                    # always stores a fill value; without an explicit producer
                    # assignment it lands here.  Even when fill-value attributes
                    # are present (e.g. _FillValue=-9999), the producer's chosen
                    # sentinel is already in `explicit` — the default zero is
                    # still ambiguous and must not be silently replaced.
                    uncertain.add(native)
                else:
                    # Non-default native fill: the producer explicitly chose
                    # this value, so it is intentional.
                    explicit.add(native)
        except (TypeError, ValueError, RuntimeError):
            # h5py raises RuntimeError when the producer never set a fill value
            # ("fill value is undefined") — treat as no native sentinel.
            pass

        return explicit, uncertain

    def _list_datasets(self):
        """Walk the file and collect metadata for every HDF5 dataset."""
        datasets = []
        with h5py.File(self.file_path, "r") as f:

            def visitor(name, obj):
                if isinstance(obj, h5py.Dataset):
                    datasets.append(
                        {
                            "path": name,
                            "shape": tuple(int(s) for s in obj.shape),
                            "ndim": int(obj.ndim),
                            "dtype": str(obj.dtype),
                            "size": int(obj.size),
                        }
                    )

            f.visititems(visitor)
        return datasets

    def _list_hdf5_groups(self):
        """Return HDF5 group paths (excluding the root group)."""
        groups = []
        with h5py.File(self.file_path, "r") as f:

            def visitor(name, obj):
                if isinstance(obj, h5py.Group):
                    groups.append(name)

            f.visititems(visitor)
        return groups

    def _build_picker_groups(self, datasets):
        """Build selectable groups for the dataset picker UI.

        Groups come from (deepest first) HDF5 group subtrees with 2+ datasets,
        then dot-prefix siblings at the file root (e.g. ``D1.*``).
        """
        paths = {ds["path"] for ds in datasets}
        assigned = set()
        groups = {}

        for group_path in sorted(self._list_hdf5_groups(), key=len, reverse=True):
            prefix = f"{group_path}/"
            members = sorted(p for p in paths if p.startswith(prefix) and p not in assigned)
            if len(members) >= 2:
                groups[group_path] = {
                    "id": group_path,
                    "label": group_path,
                    "type": "hdf5_group",
                    "dataset_paths": members,
                }
                assigned.update(members)

        prefix_map = {}
        for ds in datasets:
            path = ds["path"]
            if path in assigned or "/" in path or "." not in path:
                continue
            prefix = path.split(".", 1)[0]
            prefix_map.setdefault(prefix, []).append(path)

        for prefix, members in prefix_map.items():
            if len(members) >= 2 and prefix not in groups:
                groups[prefix] = {
                    "id": prefix,
                    "label": prefix,
                    "type": "prefix",
                    "dataset_paths": sorted(members),
                }
                assigned.update(members)

        return sorted(groups.values(), key=lambda group: group["label"].lower())

    def _is_pandas_pytables_store(self):
        """True for pandas HDFStore / PyTables frame layouts (e.g. adult.h5)."""
        with h5py.File(self.file_path, "r") as f:
            if "PYTABLES_FORMAT_VERSION" in f.attrs:
                return True

            def visitor(_name, obj):
                if isinstance(obj, h5py.Group):
                    pandas_type = obj.attrs.get("pandas_type")
                    if pandas_type in (b"frame", "frame"):
                        raise StopIteration

            try:
                f.visititems(visitor)
            except StopIteration:
                return True
        return False

    def _is_incompatible_root_layout(self, datasets):
        """True when several root-level 1D arrays have mismatched lengths.

        Files like map_f_case_16p.h5 expose many sibling datasets at ``/`` with
        different shapes. Flattening them into one column is misleading; callers
        should list datasets via parse() and load a specific path instead.
        """
        root = [ds for ds in datasets if "/" not in ds["path"]]
        if len(root) < 2:
            return False
        if not all(ds["ndim"] == 1 for ds in root):
            return False
        lengths = {ds["shape"][0] for ds in root}
        return len(lengths) > 1

    def _is_grouped_hierarchical_layout(self, datasets):
        """True for station-grouped files (EQSIM/rechdf5) with mixed 1D lengths.

        Root may hold only a few scalars while waveforms and metadata live under
        repeated group subtrees (``S_01_01/X``, ``S_01_01/Y``, …).  Pandas
        HDFStore files are excluded so ``adult.h5`` keeps auto-reading.
        """
        if self._is_pandas_pytables_store():
            return False

        nested = [ds for ds in datasets if "/" in ds["path"]]
        if len(nested) < 4:
            return False

        groups = self._build_picker_groups(datasets)
        if len(groups) < 2:
            return False

        lengths = set()
        for ds in nested:
            if ds["ndim"] == 1 and ds["shape"]:
                lengths.add(ds["shape"][0])
        return len(lengths) > 1

    def _needs_dataset_selection(self, datasets):
        return self._is_incompatible_root_layout(datasets) or self._is_grouped_hierarchical_layout(
            datasets
        )

    def inventory(self):
        """Summarize datasets and classify the overall layout."""
        datasets = self._list_datasets()
        if not datasets:
            layout = "empty"
        elif len(datasets) == 1:
            layout = "single_dataset"
        elif self._needs_dataset_selection(datasets):
            layout = "multi_dataset"
        else:
            layout = "legacy"
        groups = self._build_picker_groups(datasets) if layout == "multi_dataset" else []
        return {"type": layout, "datasets": datasets, "groups": groups}

    def _normalize_selected_keys(self, keys):
        if isinstance(keys, str):
            keys = [key.strip() for key in keys.split(",") if key.strip()]
        return [str(key) for key in keys if key]

    def _get_selected_dataset_keys(self):
        """Return dataset paths chosen in the Flask session or passed explicitly."""
        if self._explicit_selected_keys is not None:
            return self._normalize_selected_keys(self._explicit_selected_keys)
        try:
            keys = session.get("selected_keys") or []
            return self._normalize_selected_keys(keys)
        except RuntimeError:
            return []

    def _column_name_from_path(self, path, used_names):
        """Prefer the full dataset path so group/station context is preserved.

        Examples: ``S_01_01/X``, ``D1.fill_starts``. Falls back only if the full
        path is already used as a column name (duplicate selection).
        """
        full = path.strip("/") or path
        if full not in used_names:
            return full
        short = path.split("/")[-1] or path
        if short not in used_names:
            return short
        dotted = full.replace("/", ".")
        if dotted not in used_names:
            return dotted
        suffix = 2
        while f"{full}_{suffix}" in used_names:
            suffix += 1
        return f"{full}_{suffix}"

    def _read_compatible_dataset_paths(self, paths):
        """Merge multiple same-length 1D datasets into one DataFrame."""
        if not paths:
            return None

        columns = {}
        expected_len = None

        for path in paths:
            with h5py.File(self.file_path, "r") as f:
                if path not in f:
                    self.logger.warning("HDF5 dataset path not found: %s", path)
                    return None
                obj = f[path]
                if not isinstance(obj, h5py.Dataset):
                    self.logger.warning("HDF5 path is not a dataset: %s", path)
                    return None

                data = obj[()]
                data = self._apply_fill_values(data, obj, path)

                if getattr(data, "ndim", 0) != 1:
                    self.logger.warning(
                        "HDF5 multi-select requires 1D datasets; '%s' has ndim=%s",
                        path,
                        getattr(data, "ndim", None),
                    )
                    return None

                length = int(data.shape[0])
                if expected_len is None:
                    expected_len = length
                elif length != expected_len:
                    self.logger.warning(
                        "HDF5 selected datasets have incompatible lengths "
                        "(%d vs %d); cannot merge into one table.",
                        expected_len,
                        length,
                    )
                    return None

                col_name = self._column_name_from_path(path, set(columns))
                columns[col_name] = data

        df = pd.DataFrame(columns)
        df = self._decode_bytes(df)
        df.columns = [str(col) for col in df.columns]
        if df.empty:
            return None
        return df

    def _apply_fill_values(self, data, dataset, name):
        """Replace fill-value sentinels with NaN for numeric dataset arrays."""
        if not (hasattr(data, "dtype") and data.dtype.kind in ("f", "i", "u")):
            return data

        explicit_fills, _uncertain_fills = self._collect_fill_values(dataset)
        if not explicit_fills:
            return data

        matched = {fv for fv in explicit_fills if np.any(data == fv)}
        if not matched:
            return data

        mask = np.zeros(data.shape, dtype=bool)
        for fv in matched:
            mask |= data == fv
        n_replaced = int(mask.sum())

        self.logger.info(
            f"Dataset '{name}': replaced "
            f"{n_replaced}/{data.size} value(s) "
            f"matching explicit fill sentinel(s) "
            f"{matched} with NaN."
        )

        data = data.astype(np.float64)
        data[mask] = np.nan
        return data

    def _decode_bytes(self, df):
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].apply(
                    lambda x: x.decode("utf-8") if isinstance(x, bytes) else x
                )
        return df

    def _read_dataset_path(self, path):
        """Load one HDF5 dataset path into a DataFrame."""
        with h5py.File(self.file_path, "r") as f:
            if path not in f:
                self.logger.warning("HDF5 dataset path not found: %s", path)
                return None
            obj = f[path]
            if not isinstance(obj, h5py.Dataset):
                self.logger.warning("HDF5 path is not a dataset: %s", path)
                return None

            data = obj[()]
            data = self._apply_fill_values(data, obj, path)

            col_name = self._column_name_from_path(path, set())
            if getattr(data, "ndim", 0) == 0:
                df = pd.DataFrame({col_name: [data]})
            elif data.ndim == 1:
                df = pd.DataFrame({col_name: data})
            else:
                try:
                    df = pd.DataFrame(data)
                except Exception:
                    df = pd.DataFrame(data.tolist())
                df.columns = [str(col) for col in df.columns]

        df = self._decode_bytes(df)
        df.columns = [str(col) for col in df.columns]
        if df.empty:
            return None
        return df

    def read(self):
        try:
            inv = self.inventory()
            if inv["type"] == "multi_dataset":
                selected = self._get_selected_dataset_keys()
                if len(selected) == 1:
                    return self._read_dataset_path(selected[0])
                if len(selected) > 1:
                    return self._read_compatible_dataset_paths(selected)
                n = len(inv["datasets"])
                self.logger.warning(
                    "HDF5 file has %d datasets in an incompatible layout; "
                    "refusing to flatten into one table. "
                    "Use parse() / inventory() to list paths and select compatible ones.",
                    n,
                )
                return None
            if inv["type"] == "empty":
                self.logger.warning("No datasets found in HDF5 file")
                return None

            rows = []
            # Clean up byte strings in all object columns

            def decode_bytes(df):
                for col in df.columns:
                    if df[col].dtype == object:
                        df[col] = df[col].apply(
                            lambda x: x.decode("utf-8") if isinstance(x, bytes) else x
                        )
                return df

            def convert_numpy_types(obj):
                """Recursively convert numpy types to Python native types"""
                try:
                    if hasattr(obj, 'item'):  # numpy scalar
                        return obj.item()
                    elif isinstance(obj, (list, tuple)):
                        return [convert_numpy_types(item) for item in obj]
                    elif isinstance(obj, dict):
                        return {str(k): convert_numpy_types(v) for k, v in obj.items()}
                    elif hasattr(obj, 'dtype'):  # numpy array
                        if obj.size == 1:  # Single element array
                            return obj.item()
                        else:  # Multi-element array
                            return obj.tolist()
                    else:
                        return obj
                except Exception as e:
                    self.logger.warning(f"Error converting numpy type: {e}")
                    return str(obj)  # Fallback to string representation

            def recurse(name, obj, path=[]):
                try:
                    if isinstance(obj, h5py.Dataset):
                        data = obj[()]
                        data = self._apply_fill_values(data, obj, name)
                        # If it's a 1D or structured dataset, load it into dicts
                        if isinstance(data, (list, tuple)) or hasattr(data, "dtype"):
                            try:
                                df = pd.DataFrame(data)
                            except Exception:
                                df = pd.DataFrame(data.tolist())  # base
                            for _, row in df.iterrows():
                                try:
                                    row_dict = row.to_dict()
                                    # Convert any numpy types to Python native types
                                    row_dict = convert_numpy_types(row_dict)
                                    rows.append(row_dict)
                                except Exception as e:
                                    self.logger.warning(f"Error processing row: {e}")
                                    # Try to process the row with basic conversion
                                    try:
                                        basic_row = {}
                                        for col in row.index:
                                            try:
                                                value = row[col]
                                                if hasattr(value, 'item'):
                                                    basic_row[str(col)] = value.item()
                                                else:
                                                    basic_row[str(col)] = str(value)
                                            except Exception:
                                                basic_row[str(col)] = str(value)
                                        rows.append(basic_row)
                                    except Exception as e2:
                                        self.logger.warning(f"Failed to process row even with basic conversion: {e2}")
                                        continue
                        else:
                            # Scalar or flat dataset - ensure data is hashable
                            try:
                                # Convert any numpy types to Python native types
                                data = convert_numpy_types(data)
                                row_dict = {"value": data}
                                rows.append(row_dict)
                            except Exception as e:
                                self.logger.warning(f"Error processing scalar data: {e}")
                                # Try basic conversion
                                try:
                                    if hasattr(data, 'item'):
                                        row_dict = {"value": data.item()}
                                    else:
                                        row_dict = {"value": str(data)}
                                    rows.append(row_dict)
                                except Exception as e2:
                                    self.logger.warning(f"Failed to process scalar data even with basic conversion: {e2}")
                                    # Skip this data point
                                    pass
                except Exception as e:
                    self.logger.warning(f"Error in recurse function: {e}")
                    return

            with h5py.File(self.file_path, "r") as f:

                def visit(name, obj):
                    recurse(name, obj, name.strip("/").split("/"))

                f.visititems(visit)
            df = pd.DataFrame(rows)
            df = decode_bytes(df)

            # Ensure all column names are strings to avoid numpy array issues
            if hasattr(df, 'columns') and len(df.columns) > 0:
                df.columns = [str(col) for col in df.columns]

            # Check if DataFrame is empty and log warning
            if df.empty:
                self.logger.warning("No data was successfully processed from HDF5 file")
                return None

            return df
        except Exception as e:
            self.logger.error(f"Error while reading: {e}")
            return None

    def parse(self):
        datasets = self._list_datasets()
        paths = [ds["path"] for ds in datasets]
        self.logger.info("dataset paths found: %s", paths)
        return paths

    def filter(self, kept_keys):
        if isinstance(kept_keys, str):
            kept_keys = kept_keys.split(",")
        # Ensure all keys are strings and hashable to avoid "unhashable type" errors
        filtered_keys = set()
        for g in kept_keys:
            try:
                # Convert to string and ensure it's hashable
                key_str = str(g).strip("/")
                # Test if it's hashable by trying to add to set
                filtered_keys.add(key_str)
            except (TypeError, ValueError) as e:
                # If conversion fails, skip this key and log the error
                self.logger.warning(f"Skipping unhashable key {g}: {e}")
                continue

        new_file_name = (
            f"filtered_{uuid.uuid4().hex}_{session.get('uploaded_file_name')}"
        )
        new_file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], new_file_name)
        with (
            h5py.File(self.file_path, "r") as src,
            h5py.File(new_file_path, "w") as tgt,
        ):

            def copy_group(path, src_group, tgt_group):
                for name, obj in src_group.items():
                    full_path = f"{path}/{name}".strip("/")
                    if isinstance(obj, h5py.Group):
                        if full_path in filtered_keys:
                            tgt_subgroup = tgt_group.create_group(name)
                            copy_group(full_path, obj, tgt_subgroup)
                        else:
                            copy_group(full_path, obj, tgt_group)
                    elif isinstance(obj, h5py.Dataset):
                        if path.strip("/") in filtered_keys:
                            tgt_group.create_dataset(name, data=obj[()])

            copy_group("", src, tgt)

        return new_file_path
