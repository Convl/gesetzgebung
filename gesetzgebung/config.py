
from elasticsearch import Elasticsearch
import os
import locale
from dotenv import load_dotenv
from flask_apscheduler import APScheduler
from gesetzgebung.flask_file import app
from gesetzgebung.database import db
from gesetzgebung.daily_update import daily_update

load_dotenv()

locale.setlocale(locale.LC_TIME, 'de_DE.UTF-8')

POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD")
POSTGRES_HOST = "localhost"
ES_USER = os.environ.get("ES_USER")
ES_PASSWORD = os.environ.get("ES_PASSWORD")

class Config:
    SCHEDULER_API_ENABLED = True

app.config['SQLALCHEMY_DATABASE_URI'] = f"postgresql://postgres:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:5432/gesetze"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config.from_object(Config)

db.init_app(app)

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()
# scheduler.add_job(id="daily_update", func=daily_update, trigger="interval", hours=12)

es = Elasticsearch("http://localhost:9200", basic_auth=(ES_USER, ES_PASSWORD))
