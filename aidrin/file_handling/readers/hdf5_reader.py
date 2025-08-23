import os
import uuid

import h5py
import pandas as pd
from flask import current_app, session

from aidrin.file_handling.readers.base_reader import BaseFileReader


class hdf5Reader(BaseFileReader):
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
                if hasattr(obj, 'item'):  # numpy scalar
                    return obj.item()
                elif isinstance(obj, (list, tuple)):
                    return [convert_numpy_types(item) for item in obj]
                elif isinstance(obj, dict):
                    return {str(k): convert_numpy_types(v) for k, v in obj.items()}
                elif hasattr(obj, 'dtype'):  # numpy array
                    return obj.tolist()
                else:
                    return obj

            def recurse(name, obj, path=[]):
                try:
                    if isinstance(obj, h5py.Dataset):
                        data = obj[()]
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
        kept_keys = set()
        for g in kept_keys:
            try:
                # Convert to string and ensure it's hashable
                key_str = str(g).strip("/")
                # Test if it's hashable by trying to add to set
                kept_keys.add(key_str)
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
                        if full_path in kept_keys:
                            tgt_subgroup = tgt_group.create_group(name)
                            copy_group(full_path, obj, tgt_subgroup)
                        else:
                            copy_group(full_path, obj, tgt_group)
                    elif isinstance(obj, h5py.Dataset):
                        if path.strip("/") in kept_keys:
                            tgt_group.create_dataset(name, data=obj[()])

            copy_group("", src, tgt)

        return new_file_path
