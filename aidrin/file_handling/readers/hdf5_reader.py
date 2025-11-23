import os
import uuid
import random
import h5py
import pandas as pd
import numpy as np
from flask import current_app, session

from aidrin.file_handling.readers.base_reader import BaseFileReader


class hdf5Reader(BaseFileReader):
    def read(self):
        try:
            # Limit number of rows using random sampling
            MAX_ROWS = 2000
            rows = []
            count = 0
            

            # Clean up byte strings in all object columns
            def decode_bytes(df):
                for col in df.columns:
                    if df[col].dtype == object:
                        df[col] = df[col].apply(
                            lambda x: x.decode("utf-8") if isinstance(x, (bytes, bytearray, np.bytes_)) else x
                        )
                return df

            # Expand structured numpy dtypes into list of dicts
            def structured_to_records(data):
                try:
                    if isinstance(data, np.ndarray):
                        if getattr(data, "dtype", None) is not None and data.dtype.names:
                            return [dict(zip(data.dtype.names, row)) for row in data]
                except Exception:
                    pass
                return data

            # Convert numpy types to Python native types
            def convert_numpy_types(obj):
                try:
                    if hasattr(obj, "item"):
                        return obj.item()
                    elif isinstance(obj, (list, tuple)):
                        return [convert_numpy_types(x) for x in obj]
                    elif isinstance(obj, dict):
                        return {str(k): convert_numpy_types(v) for k, v in obj.items()}
                    elif isinstance(obj, np.ndarray):
                        if obj.size == 1:
                            return obj.item()
                        return [convert_numpy_types(x) for x in obj.tolist()]
                    return obj
                except Exception:
                    return str(obj)

            # Random sampling helper
            def add_row(row_dict):
                nonlocal count
                count += 1
                if len(rows) < MAX_ROWS:
                    rows.append(row_dict)
                else:
                    j = random.randint(1, count)
                    if j <= MAX_ROWS:
                        rows[j - 1] = row_dict

            # Process a chunk of data (structured dtype, ND flattening, sampling)
            def process_data_chunk(data):
                data = structured_to_records(data)

                # ND flattening for multidimensional arrays
                if isinstance(data, np.ndarray) and hasattr(data, "ndim") and data.ndim > 2:
                    try:
                        data = np.ascontiguousarray(data).reshape(data.shape[0], -1)
                    except Exception:
                        return

                # Fast-path for simple 1D arrays
                if isinstance(data, np.ndarray) and data.ndim == 1:
                    for val in data:
                        try:
                            row_val = convert_numpy_types(val)
                            add_row({"value": row_val})
                        except Exception:
                            continue
                    return

                # Handle table-like datasets
                if isinstance(data, (list, tuple)) or hasattr(data, "dtype"):
                    try:
                        df = pd.DataFrame(data)
                    except Exception:
                        try:
                            df = pd.DataFrame(data.tolist())
                        except Exception:
                            return

                    for _, row in df.iterrows():
                        try:
                            row_dict = convert_numpy_types(row.to_dict())
                            add_row(row_dict)
                        except Exception:
                            try:
                                basic_row = {}
                                for col in row.index:
                                    val = row[col]
                                    if hasattr(val, "item"):
                                        basic_row[str(col)] = val.item()
                                    else:
                                        basic_row[str(col)] = str(val)
                                add_row(basic_row)
                            except Exception:
                                continue
                else:
                    try:
                        val = convert_numpy_types(data)
                        add_row({"value": val})
                    except Exception:
                        try:
                            if hasattr(data, "item"):
                                add_row({"value": data.item()})
                            else:
                                add_row({"value": str(data)})
                        except Exception:
                            return

            # Chunked dataset reading + sampling
            def recurse(name, obj, path=[]):
                if isinstance(obj, h5py.Dataset):
                    shape = getattr(obj, "shape", None)

                    # Chunk mode for any large dataset (Option 2)
                    if shape is not None and len(shape) > 0 and shape[0] > 10000:
                        step = 10000
                        for i in range(0, shape[0], step):
                            try:
                                chunk = obj[i:i+step]
                                process_data_chunk(chunk)
                            except Exception:
                                break
                    else:
                        try:
                            data = obj[()]
                            process_data_chunk(data)
                        except Exception:
                            return

            # Traverse all datasets
            with h5py.File(self.file_path, "r") as f:
                def visit(name, obj):
                    recurse(name, obj, name.strip("/").split("/"))
                f.visititems(visit)

            # Create final DataFrame
            df = pd.DataFrame(rows)
            df = decode_bytes(df)

            if hasattr(df, "columns") and len(df.columns) > 0:
                df.columns = [str(col) for col in df.columns]

            if df.empty:
                self.logger.warning("No data was successfully processed from HDF5 file")
                return None

            return df

        except Exception as e:
            self.logger.error(f"Error while reading: {e}")
            return None

    def parse(self):
        def recurse(data):
            try:
                items = list(data.items())
                for name, obj in items:
                    try:
                        full_path = str(name)
                        if isinstance(obj, h5py.Group):
                            group_names.append(full_path)
                            recurse(obj)
                    except (TypeError, ValueError):
                        continue
            except Exception:
                pass
            return group_names

        with h5py.File(self.file_path, "r") as f:
            group_names = []
            recurse(f)
            self.logger.info(f"group names found: {group_names}")
            return group_names

    def filter(self, kept_keys):
        if isinstance(kept_keys, str):
            kept_keys = kept_keys.split(",")

        filtered_keys = set()
        for g in kept_keys:
            try:
                key_str = str(g).strip("/")
                filtered_keys.add(key_str)
            except (TypeError, ValueError) as e:
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

