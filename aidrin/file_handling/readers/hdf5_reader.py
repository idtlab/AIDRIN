import os
import uuid

import h5py
import numpy as np
import pandas as pd
from flask import current_app, session

from aidrin.file_handling.readers.base_reader import BaseFileReader


class hdf5Reader(BaseFileReader):
    def __init__(self, file_path: str, logger, fill_values=None):
        super().__init__(file_path, logger)
        # Optional user-supplied fill values merged with auto-detected ones.
        # Accepts any iterable of scalars, e.g. fill_values=[-9999, -1].
        self.fill_values = set(fill_values) if fill_values is not None else set()

    def _collect_fill_values(self, dataset):
        """Return a set of numeric sentinels that represent missing data for
        this dataset, drawn from four sources in priority order:

        1. User-supplied values passed at construction time.
        2. ``_FillValue`` attribute — NetCDF/CF convention, present in
           virtually all climate, oceanography, and atmospheric HDF5 files.
        3. ``missing_value`` attribute — older NetCDF convention; may be a
           scalar or a 1-D array listing multiple sentinels.
        4. ``dataset.fillvalue`` — the HDF5-native fill value written into
           the file at dataset-creation time (always present; defaults to
           0 / 0.0 when the producer did not set one explicitly).

        Only numeric values are collected; non-numeric sentinels (e.g. byte
        strings in variable-length string datasets) are silently skipped
        because the dtype guard in read() filters those datasets out before
        this method is called.
        """
        collected = set(self.fill_values)

        for attr_name in ("_FillValue", "missing_value"):
            if attr_name in dataset.attrs:
                raw = dataset.attrs[attr_name]
                for v in np.atleast_1d(raw).ravel():
                    try:
                        collected.add(float(v))
                    except (TypeError, ValueError):
                        pass

        try:
            collected.add(float(dataset.fillvalue))
        except (TypeError, ValueError):
            pass

        return collected

    def read(self):
        try:
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
                        # Translate all fill-value sentinels to NaN so that
                        # pd.isnull()-based metrics (completeness, outliers, …)
                        # correctly detect missing data.  Sentinels are collected
                        # from the HDF5 native fillvalue, the _FillValue and
                        # missing_value dataset attributes (NetCDF/CF convention),
                        # and any values supplied by the caller at construction time.
                        if hasattr(data, "dtype") and data.dtype.kind in ("f", "i", "u"):
                            fill_vals = self._collect_fill_values(obj)
                            if fill_vals:
                                mask = np.zeros(data.shape, dtype=bool)
                                for fv in fill_vals:
                                    mask |= data == fv
                                if mask.any():
                                    data = data.astype(np.float64)
                                    data[mask] = np.nan
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
        # Recursively find all group names in the HDF5 file
        def recurse(data):
            try:
                # Convert items() to a list first to avoid iteration issues
                items = list(data.items())
                for name, obj in items:
                    try:
                        # Ensure name is a string and hashable to avoid "unhashable type" errors
                        full_path = str(name)

                        if isinstance(obj, h5py.Group):
                            group_names.append(full_path)
                            recurse(obj)
                    except (TypeError, ValueError) as e:
                        # If conversion fails, skip this key and log the error
                        self.logger.warning(f"Skipping unhashable key {name}: {e}")
                        continue
            except Exception as e:
                self.logger.error(f"Error during recursion: {e}")
            return group_names

        with h5py.File(self.file_path, "r") as f:
            group_names = []
            recurse(f)
            self.logger.info(f"group names found: {group_names}")
            return group_names

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
