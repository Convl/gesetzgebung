
# from elasticsearch import Elasticsearch
from elasticsearch7 import Elasticsearch
import os
import datetime
import locale
from dotenv import load_dotenv
from flask_apscheduler import APScheduler
from gesetzgebung.flask_file import app
from gesetzgebung.database import db
from gesetzgebung.es_file import *
from gesetzgebung.daily_update import daily_update

load_dotenv()

# locale.setlocale(locale.LC_TIME, 'de_DE.utf8')

POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD")
POSTGRES_HOST = "localhost"
DATABASE_URI = os.environ.get("DATABASE_URL", '').replace('postgres://', 'postgresql://') or f"postgresql://postgres:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:5432/gesetze"

class Config:
    SCHEDULER_API_ENABLED = True

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config.from_object(Config)

db.init_app(app)

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()
scheduler.add_job(id="daily_update", func=daily_update, trigger="interval", hours=24)
