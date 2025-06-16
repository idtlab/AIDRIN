from flask import Flask, session, redirect, request
import pandas as pd
import numpy as np
import logging
# Parses the uploaded file into a pandas database 
def read_file(path,name,type):
    time_log = logging.getLogger('aidrin')
    file_upload_time_log = logging.getLogger('file_upload')

    file_upload_time_log.info("file parsing intiaited...")
    uploaded_file_path = path
    uploaded_file_name = name
    uploaded_file_type = type

    if not uploaded_file_path and uploaded_file_name:
        return redirect(request.url)
    
    #default result
    readFile = None
    #csv
    if uploaded_file_type==('.csv'):
        readFile = pd.read_csv(uploaded_file_path, index_col=False)
    #npz
    if uploaded_file_type==('.npz'):
        npz_data = np.load(uploaded_file_path,allow_pickle=True)
        readFile = pd.DataFrame({key: npz_data[key] for key in npz_data.files})
    #excel
    if uploaded_file_type==('.xls,.xlsb,.xlsx,.xlsm'):
        readFile = pd.read_excel(uploaded_file_path)
    #json
    if uploaded_file_type==('.json'):
        readFile = pd.read_json(uploaded_file_path)
    #hdf
    if uploaded_file_type==('.h5'):
        readFile = pd.read_hdf(uploaded_file_path)
    file_upload_time_log.info("file successfully parsed!")
    return readFile, uploaded_file_path, uploaded_file_name

