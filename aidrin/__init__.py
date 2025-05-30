from flask import Flask
import os
import logging

#initialize app
app = Flask(__name__)
app.secret_key = "aidrin"        
          
# Create upload folder (Disc storage)
UPLOAD_FOLDER = os.path.join(app.root_path, "datasets", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Initialize temporary results cache (RAM storage--change to database?)
app.TEMP_RESULTS_CACHE = {}

# Initialize time log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s', #timestamp, logger name, log level, message
    handlers=[logging.FileHandler('aidrin.log'), logging.StreamHandler()] # log to file and console
)
logging.getLogger('werkzeug').setLevel(logging.WARNING) # Supress werkzeug logs
#link to main after app is created
from . import main