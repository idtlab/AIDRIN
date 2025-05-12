from flask import Flask
import os

#initialize app
app = Flask(__name__)
app.secret_key = "aidrin"        
          
# create upload folder
UPLOAD_FOLDER = os.path.join(app.root_path, "datasets", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

#link to main after app is created
from . import main