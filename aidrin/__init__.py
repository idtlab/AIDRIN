from flask import Flask
import os
import logging

#initialize app
app = Flask(__name__)
app.secret_key = "aidrin"        
          
# Create upload folder (Disc storage)
UPLOAD_FOLDER = os.path.join(app.root_path, "data", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Initialize temporary results cache (RAM storage--change to database?)
app.TEMP_RESULTS_CACHE = {}

# Initialize time log
log_path = os.path.join(os.path.dirname(__file__), 'data', 'logs', 'aidrin.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s', #timestamp, logger name, log level, message
    handlers=[logging.FileHandler(log_path), logging.StreamHandler()] # log to file and console
)

#Supress workzeug logs for POST and GET requests to declutter -- but keep start up messages
class SuppressRequestsFilter(logging.Filter):
    def filter(self, record):
        # Suppress lines like "GET / HTTP/1.1"
        return not ('GET' in record.getMessage() or 'POST' in record.getMessage())
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.INFO)
werkzeug_logger.addFilter(SuppressRequestsFilter())

#link to main after app is created
from . import main