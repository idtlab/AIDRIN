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

# Celery configuration
app.config['CELERY_BROKER_URL'] = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
app.config['CELERY_RESULT_BACKEND'] = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

# Initialize temporary results cache (RAM storage--change to database?)
app.TEMP_RESULTS_CACHE = {}

# Initialize time log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s', #timestamp, logger name, log level, message
    handlers=[logging.FileHandler('aidrin.log'), logging.StreamHandler()] # log to file and console
)
logging.getLogger('werkzeug').setLevel(logging.WARNING) # Supress werkzeug logs

# Initialize Celery
from .celery_app import make_celery
celery = make_celery(app)

#link to main after app is created
from . import main