import zarr
import numpy as np
import pandas as pd
from aidrin.file_handling.readers.base_reader import BaseFileReader


class zarrReader(BaseFileReader):
    # zarr is similar to hdf5 - both store data in groups and arrays
    # i learned this when i was reading about scientific data formats
    # zarr is newer and works better for cloud storage compared to hdf5

    def read(self):
        try:
            rows = []

            # open the zarr store - can be a folder or zip file
            store = zarr.open(self.file_path, mode='r')

            def recurse(group, prefix=''):
                # going through all arrays inside zarr store
                # zarr stores data in groups like folders in a computer
                for key in group.keys():
                    full_key = f"{prefix}/{key}".strip('/')
                    item = group[key]

                    if isinstance(item, zarr.Array):
                        try:
                            # convert zarr array to numpy then to dataframe
                            data = item[:]

                            # handle fill values similar to hdf5 reader
                            if hasattr(data, 'dtype') and data.dtype.kind in ('f', 'i', 'u'):
                                fill_val = item.fill_value
                                if fill_val is not None and fill_val != 0:
                                    data = data.astype(np.float64)
                                    data[data == fill_val] = np.nan

                            # flatten to 2d if needed
                            if data.ndim > 2:
                                data = data.reshape(-1, data.shape[-1])
                            elif data.ndim == 1:
                                data = data.reshape(-1, 1)

                            df = pd.DataFrame(data)
                            df.columns = [f"{full_key}_{c}" 
                                         for c in df.columns]

                            for _, row in df.iterrows():
                                rows.append(row.to_dict())

                        except Exception as e:
                            self.logger.warning(
                                f"could not read array {full_key}: {e}"
                            )

                    elif isinstance(item, zarr.Group):
                        # if its a group go deeper into it
                        recurse(item, full_key)

            recurse(store)

            if not rows:
                self.logger.warning("no data found in zarr file")
                return None

            df = pd.DataFrame(rows)
            self.logger.info(f"zarr file read successfully, shape: {df.shape}")
            return df

        except Exception as e:
            self.logger.error(f"error reading zarr file: {e}")
            return None

    def parse(self):
        # returns all group names inside the zarr store
        # similar to parse() in hdf5_reader
        try:
            store = zarr.open(self.file_path, mode='r')
            group_names = []

            def collect_groups(group, prefix=''):
                for key in group.keys():
                    full_key = f"{prefix}/{key}".strip('/')
                    item = group[key]
                    if isinstance(item, zarr.Group):
                        group_names.append(full_key)
                        collect_groups(item, full_key)

            collect_groups(store)
            self.logger.info(f"zarr groups found: {group_names}")
            return group_names

        except Exception as e:
            self.logger.error(f"error parsing zarr file: {e}")
            return None

    def filter(self, kept_keys):
        # filters zarr store to keep only selected groups
        # useful when zarr file has many groups and user wants specific ones
        try:
            if isinstance(kept_keys, str):
                kept_keys = [k.strip() for k in kept_keys.split(',')]

            kept_keys = set(kept_keys)
            src = zarr.open(self.file_path, mode='r')

            # create a new in memory store with only kept groups
            filtered = zarr.group()

            def copy_filtered(src_group, tgt_group, prefix=''):
                for key in src_group.keys():
                    full_key = f"{prefix}/{key}".strip('/')
                    item = src_group[key]

                    if isinstance(item, zarr.Array):
                        if prefix in kept_keys or full_key in kept_keys:
                            tgt_group.create_dataset(
                                key, data=item[:], 
                                chunks=item.chunks
                            )
                    elif isinstance(item, zarr.Group):
                        if full_key in kept_keys:
                            sub = tgt_group.require_group(key)
                            copy_filtered(item, sub, full_key)
                        else:
                            copy_filtered(item, tgt_group, full_key)

            copy_filtered(src, filtered)
            return filtered

        except Exception as e:
            self.logger.error(f"error filtering zarr file: {e}")
            return None