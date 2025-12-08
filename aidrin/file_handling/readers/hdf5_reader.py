import os
import uuid
import json
import h5py
import pandas as pd
import numpy as np
from flask import current_app, session

from aidrin.file_handling.readers.base_reader import BaseFileReader


class hdf5Reader(BaseFileReader):
    def read(self):
        try:
            CHUNK = 10_000


            dfs = []
            total_rows = 0

            def decode_bytes_inplace(df):
                if df is None or df.empty:
                    return df
                obj_cols = df.select_dtypes(include=["object"]).columns
                for col in obj_cols:
                    df[col] = df[col].map(
                        lambda x: x.decode("utf-8")
                        if isinstance(x, (bytes, bytearray, np.bytes_))
                        else x
                    )
                return df

            def make_cells_hashable_inplace(df):
                if df is None or df.empty:
                    return df

                def to_hashable(x):
                    if isinstance(x, (list, dict, set, tuple, np.ndarray)):
                        try:
                            return json.dumps(x, default=str, ensure_ascii=False)
                        except Exception:
                            return str(x)
                    return x

                obj_cols = df.select_dtypes(include=["object"]).columns
                for col in obj_cols:
                    df[col] = df[col].map(to_hashable)
                return df

            def df_from_any(data):
                if isinstance(data, np.ndarray):
                    if getattr(data.dtype, "names", None):
                        return pd.DataFrame.from_records(data)

                    if data.ndim == 0:
                        return pd.DataFrame(
                            [{"value": data.item() if isinstance(data, np.generic) else data}]
                        )

                    if data.ndim == 1:
                        return pd.DataFrame({"value": data})

                    if data.ndim > 2:
                        data = np.ascontiguousarray(data).reshape(data.shape[0], -1)

                    if data.ndim == 2:
                        return pd.DataFrame(data)

                    return pd.DataFrame({"value": [str(data)]})

                if isinstance(data, (list, tuple)):
                    try:
                        return pd.DataFrame(data)
                    except Exception:
                        return pd.DataFrame({"value": list(data)})

                return pd.DataFrame([{"value": data}])

            def add_df(df):
                nonlocal total_rows
                if df is None or df.empty:
                    return

                df.columns = [str(c) for c in df.columns]

                df = decode_bytes_inplace(df)
                df = make_cells_hashable_inplace(df)

                dfs.append(df)
                total_rows += len(df)

            with h5py.File(self.file_path, "r") as f:

                def handle_dataset(name, dset):
                    nonlocal total_rows
                    try:
                        shape = getattr(dset, "shape", None)
                        dtype = getattr(dset, "dtype", None)
                        self.logger.info(f"HDF5 dataset: {name} shape={shape} dtype={dtype}")

                        if shape is None or len(shape) == 0:
                            df = df_from_any(dset[()])
                            add_df(df)
                            return

                        n = int(shape[0]) if shape[0] is not None else 0
                        if n == 0:
                            df = df_from_any(dset[()])
                            add_df(df)
                            return

                        limit = n
                        if isinstance(MAX_ROWS_PER_DATASET, int):
                            limit = min(limit, MAX_ROWS_PER_DATASET)

                        for start in range(0, limit, CHUNK):
                            if isinstance(MAX_TOTAL_ROWS, int) and total_rows >= MAX_TOTAL_ROWS:
                                self.logger.warning("Stopping early due to MAX_TOTAL_ROWS cap")
                                return

                            chunk = dset[start: start + CHUNK]
                            df = df_from_any(chunk)
                            add_df(df)

                    except Exception:
                        self.logger.exception(f"Failed reading dataset: {name}")

                def visitor(name, obj):
                    if isinstance(obj, h5py.Dataset):
                        handle_dataset(name, obj)

                f.visititems(visitor)

            if not dfs:
                self.logger.warning("No data was successfully processed from HDF5 file")
                return None

            out = pd.concat(dfs, ignore_index=True, sort=False)
            return None if out.empty else out

        except Exception as e:
            self.logger.error(f"Error while reading: {e}")
            self.logger.exception("HDF5 read() failed with exception")
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
                    except (TypeError, ValueError) as e:
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

        filtered_keys = set()
        for g in kept_keys:
            try:
                key_str = str(g).strip("/")
                filtered_keys.add(key_str)
            except (TypeError, ValueError) as e:
                self.logger.warning(f"Skipping unhashable key {g}: {e}")
                continue

        new_file_name = f"filtered_{uuid.uuid4().hex}_{session.get('uploaded_file_name')}"
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


