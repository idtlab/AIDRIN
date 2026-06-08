import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader


class parquetReader(BaseFileReader):
    def read(self):
        return pd.read_parquet(self.file_path)
