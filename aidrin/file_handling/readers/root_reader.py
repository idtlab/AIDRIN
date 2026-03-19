import pandas as pd
import numpy as np
from aidrin.file_handling.readers.base_reader import BaseFileReader

try:
    import uproot
    import awkward as ak
    UPROOT_AVAILABLE = True
except ImportError:
    UPROOT_AVAILABLE = False


class rootReader(BaseFileReader):
    # ROOT is a file format developed by CERN for particle physics data
    # it stores data in a tree structure with branches and leaves
    # uproot is the python library that reads ROOT files without needing
    # the full ROOT framework installed which is very heavy
    # i learned about this format while looking at the gsoc project description
    # which specifically mentioned ROOT as one of the formats to add

    def read(self):
        if not UPROOT_AVAILABLE:
            self.logger.error(
                "uproot and awkward are required to read ROOT files. "
                "install them with: pip install uproot awkward"
            )
            return None

        try:
            rows = []

            with uproot.open(self.file_path) as root_file:
                # getting all keys in the root file
                all_keys = root_file.keys()
                self.logger.info(f"ROOT file opened. Keys found: {all_keys}")

                for key in all_keys:
                    obj = root_file[key]

                    # handling TTree objects - main data structure in ROOT
                    if isinstance(obj, uproot.behaviors.TTree.TTree):
                        self.logger.info(
                            f"reading TTree: {key} with "
                            f"{obj.num_entries} entries"
                        )
                        try:
                            # converting tree to pandas dataframe
                            # using uproot's built in pandas conversion
                            df_tree = obj.arrays(library="pd")

                            # flattening any nested columns
                            for col in df_tree.columns:
                                if df_tree[col].dtype == object:
                                    try:
                                        df_tree[col] = df_tree[col].apply(
                                            lambda x: x[0] if hasattr(x, '__len__') 
                                            and len(x) == 1 else str(x)
                                        )
                                    except Exception:
                                        df_tree[col] = df_tree[col].astype(str)

                            for _, row in df_tree.iterrows():
                                rows.append(row.to_dict())

                        except Exception as e:
                            self.logger.warning(
                                f"could not read TTree {key}: {e}"
                            )

                    # handling TH1 histograms
                    elif hasattr(obj, 'values') and hasattr(obj, 'axes'):
                        try:
                            values = obj.values()
                            axes = obj.axes()

                            if len(axes) == 1:
                                # 1d histogram
                                bin_centers = (axes[0][:-1] + axes[0][1:]) / 2
                                for center, val in zip(bin_centers, values):
                                    rows.append({
                                        f"{key}_bin_center": float(center),
                                        f"{key}_value": float(val)
                                    })
                            self.logger.info(f"read histogram: {key}")

                        except Exception as e:
                            self.logger.warning(
                                f"could not read histogram {key}: {e}"
                            )

            if not rows:
                self.logger.warning("no data found in ROOT file")
                return None

            df = pd.DataFrame(rows)
            self.logger.info(
                f"ROOT file read successfully, shape: {df.shape}"
            )
            return df

        except Exception as e:
            self.logger.error(f"error reading ROOT file: {e}")
            return None

    def parse(self):
        # returns all tree and histogram names in the ROOT file
        if not UPROOT_AVAILABLE:
            self.logger.error("uproot is required to parse ROOT files")
            return None

        try:
            with uproot.open(self.file_path) as root_file:
                keys = root_file.keys()
                self.logger.info(f"ROOT file keys: {keys}")
                return keys

        except Exception as e:
            self.logger.error(f"error parsing ROOT file: {e}")
            return None

    def filter(self, kept_keys):
        # filters ROOT file to keep only specified trees or histograms
        if not UPROOT_AVAILABLE:
            self.logger.error("uproot is required to filter ROOT files")
            return None

        try:
            if isinstance(kept_keys, str):
                kept_keys = [k.strip() for k in kept_keys.split(',')]

            kept_keys = set(kept_keys)
            rows = []

            with uproot.open(self.file_path) as root_file:
                for key in root_file.keys():
                    # stripping cycle number from key name
                    # root keys have format "name;cycle"
                    clean_key = key.split(';')[0]

                    if clean_key in kept_keys:
                        obj = root_file[key]
                        if isinstance(obj, uproot.behaviors.TTree.TTree):
                            try:
                                df_tree = obj.arrays(library="pd")
                                for _, row in df_tree.iterrows():
                                    rows.append(row.to_dict())
                            except Exception as e:
                                self.logger.warning(
                                    f"could not filter TTree {key}: {e}"
                                )

            if not rows:
                self.logger.warning("no data found after filtering")
                return None

            return pd.DataFrame(rows)

        except Exception as e:
            self.logger.error(f"error filtering ROOT file: {e}")
            return None