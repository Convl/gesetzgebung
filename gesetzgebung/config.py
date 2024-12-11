
import os
import locale
from dotenv import load_dotenv
from gesetzgebung.flask_file import app
from gesetzgebung.database import db
from gesetzgebung.es_file import *

load_dotenv()

locale.setlocale(locale.LC_TIME, 'de_DE.utf8')

DATABASE_URI = os.environ.get("DATABASE_URL", '').replace('postgres://', 'postgresql://') or os.environ.get("LOCAL_DATABASE_URL", '')
DEBUG = os.environ.get("ENV_FLAG", "") == "development"

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['DEBUG'] = DEBUG

db.init_app(app)

with app.app_context():
    db.create_all()