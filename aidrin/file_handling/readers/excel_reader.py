import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader


class excelReader(BaseFileReader):
    def read(self):
        return pd.read_excel(self.file_path)
