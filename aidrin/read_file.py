import pandas as pd
import numpy as np
import logging

#Supported file types
SUPPORTED_FILE_TYPES = [
    ('.csv', 'CSV'),
    ('.xls, .xlsb, .xlsx, .xlsm', 'Excel'),
    ('.json', 'JSON'),
    ('.npz', 'NumPy'),
    ('.h5', 'HDF5')
    #Add additional file types here using the format:
    #(file_type,file_type_name)
]

# Parses the uploaded file into a pandas database 
def read_file(file_info):
    """
    
    Parses a given file into pandas Dataframe.

    Parameters
    ----------
    file_info: tuple
        (file_path, file_name, file_type) where: 
        -file_path: str, relative or absolute path of the file.
        -file_name: str, file name. 
        -file_type: str, file format. Passed from front end select value. 
            Currently Supported:
                -CSV (.csv)
                -NumPy (.npz)
                -Excel (.xls,.xlsb,.xlsx,.xlsm)
            Limited support:
                -Json (.json)
                -HDF5 (.h5)

    Returns
    ----------
    pd.Dataframe, None, or Error
    Parsed data as a dataframe, None if the file type is not supported, or Error if processing is unsuccessful.
    
    Notes
    ----------
    To add support for new file types:
        - Add parsing logic to 'read_file' using the 'BaseTemplate' below.
        - Add file type information to the 'SUPPORTED_FILE_TYPES' list above.
    """
    # logging config
    file_upload_time_log = logging.getLogger('file_upload')
    file_upload_time_log.info("File parsing intiaited...")
    
    file_path, file_name, file_type = file_info

    if not file_path and file_name: #path and name are passed from flask, if they don't exist in session they will have None value
        file_upload_time_log.error("Missing file path or file name.")
        return None
    try:
        #default result
        df = None
        reader_map = {
            '.csv': csvReader,
            '.npz': npzReader,
            '.xls, .xlsb, .xlsx, .xlsm': excelReader,
            '.json': jsonReader,
            '.h5': hdf5Reader,
            #Add additonal file types here
        }
        if file_type in reader_map:
            df = reader_map[file_type](file_path).read()
            file_upload_time_log.info("File successfully parsed!")
        else:
            file_upload_time_log.warning("Unsupported file type: {file_type}")
       
        return df
    except Exception as e:
        file_upload_time_log.error(f"Error while File Parsing: {e}")
        return str(e)
        
class BaseFileReader:
    def __init__(self, file_path: str):
        self.file_path = file_path
    def read(self):
        raise NotImplementedError("Subclasses must implement the read() method.")

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
        return pd.read_json(self.file_path)

class hdf5Reader(BaseFileReader):
    def read(self):
        readFile = pd.read_hdf(self.file_path)

