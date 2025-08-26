import numpy as np
import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader


class npzReader(BaseFileReader):
    def read(self):
        npz_data = np.load(self.file_path, allow_pickle=True)

        # Convert numpy arrays to Python native types
        data_dict = {}
        for key in npz_data.files:
            value = npz_data[key]
            if hasattr(value, 'tolist'):
                data_dict[str(key)] = value.tolist()
            elif hasattr(value, 'item'):
                data_dict[str(key)] = value.item()
            else:
                data_dict[str(key)] = value

        df = pd.DataFrame(data_dict)

        # Ensure all column names are strings to avoid numpy array issues
        if hasattr(df, 'columns') and len(df.columns) > 0:
            df.columns = [str(col) for col in df.columns]

        return df
