import pandas as pd
import numpy as np
import json
# Use the 'BaseFileReader' template and examples below to add your own file parsing logic.
class BaseFileReader:
    def __init__(self, file_path: str, logger):
        self.file_path = file_path
        self.logger = logger
    def read(self):
        raise NotImplementedError("Subclasses must implement the read() method.")
    # Optional method: parse hierarchical group identifiers
    def parse(self):
        return None
    # Optional method: filter by keys for hierarchical data
    def filter(self,kept_keys):
        return None

class csvReader(BaseFileReader):
    def read(self):
        return pd.read_csv(self.file_path, index_col=False)
    
class npzReader(BaseFileReader):
    def read(self):
        npz_data = np.load(self.file_path,allow_pickle=True)
        return pd.DataFrame({key: npz_data[key] for key in npz_data.files})
    
class excelReader(BaseFileReader):
    def read(self):
        return pd.read_excel(self.file_path)
    
class jsonReader(BaseFileReader):
    def read(self):
        df = pd.read_json(self.file_path,typ='dict')
        df = pd.DataFrame(df.tolist())
        self.logger.info("df: %s",df)
        return df
    def parse(self):
        with open(self.file_path, 'r') as f:
            data = json.load(f)
            #only parse hierarchical data
            if isinstance(data, dict):
                self.logger.info("Keys found: %s",data.keys())
                return list(data.keys())
    def filter(self,kept_keys):
        with open(self.file_path, 'r') as f:
            data = json.load(f)
        #fix str passing
        if isinstance(kept_keys, str):
            kept_keys = kept_keys.split(',')
        # Only keep keys the user selected
        filtered_data = {k: data[k] for k in kept_keys if k in data}
        return filtered_data
            

class hdf5Reader(BaseFileReader):
    def read(self):
        return pd.read_hdf(self.file_path)

