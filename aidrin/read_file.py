from flask import Flask, session, redirect, request
import pandas as pd
import numpy as np
import logging
# Parses the uploaded file into a pandas database 
def read_file(file_info):
    file_upload_time_log = logging.getLogger('file_upload')

    file_upload_time_log.info("file parsing intiaited...")
    file_path, file_name, file_type = file_info

    if not file_path and file_name:
        return redirect(request.url)
    
    #default result
    readFile = None
    #csv
    if file_type==('.csv'):
        readFile = pd.read_csv(file_path, index_col=False)
    #npz
    if file_type==('.npz'):
        npz_data = np.load(file_path,allow_pickle=True)
        readFile = pd.DataFrame({key: npz_data[key] for key in npz_data.files})
    #excel
    if file_type==('.xls,.xlsb,.xlsx,.xlsm'):
        readFile = pd.read_excel(file_path)
    #json
    if file_type==('.json'):
        readFile = pd.read_json(file_path)
    #hdf
    if file_type==('.h5'):
        readFile = pd.read_hdf(file_path)
    file_upload_time_log.info("file successfully parsed!")
    return readFile, file_path, file_name

