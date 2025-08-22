import numpy as np
import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader


class npzReader(BaseFileReader):
    def read(self):
        npz_data = np.load(self.file_path, allow_pickle=True)
        return pd.DataFrame({key: npz_data[key] for key in npz_data.files})
