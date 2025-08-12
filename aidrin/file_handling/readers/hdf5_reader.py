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

            def recurse(name, obj, path=[]):
                if isinstance(obj, h5py.Dataset):
                    data = obj[()]
                    # If it's a 1D or structured dataset, load it into dicts
                    if isinstance(data, (list, tuple)) or hasattr(data, "dtype"):
                        try:
                            df = pd.DataFrame(data)
                        except Exception:
                            df = pd.DataFrame(data.tolist())  # base
                        for _, row in df.iterrows():
                            row_dict = row.to_dict()
                            rows.append(row_dict)
                    else:
                        # Scalar or flat dataset
                        row_dict = {"value": data}
                        rows.append(row_dict)

            with h5py.File(self.file_path, "r") as f:

                def visit(name, obj):
                    recurse(name, obj, name.strip("/").split("/"))

                f.visititems(visit)
            df = pd.DataFrame(rows)
            df = decode_bytes(df)
            return df
        except Exception as e:
            self.logger.error(f"Error while reading: {e}")

    def parse(self):
        # Recursively find all group names in the HDF5 file
        def recurse(data):
            for name, obj in data.items():
                full_path = name
                if isinstance(obj, h5py.Group):
                    group_names.append(full_path)
                    recurse(obj)
            return group_names

        with h5py.File(self.file_path, "r") as f:
            group_names = []
            recurse(f)
            self.logger.info(f"group names found: {group_names}")
            return group_names

    def filter(self, kept_keys):
        if isinstance(kept_keys, str):
            kept_keys = kept_keys.split(",")
            kept_keys = {g.strip("/") for g in kept_keys}
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
