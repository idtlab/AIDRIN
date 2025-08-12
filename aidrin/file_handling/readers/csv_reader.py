import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader


class csvReader(BaseFileReader):
    def read(self):
        return pd.read_csv(self.file_path, index_col=False)
