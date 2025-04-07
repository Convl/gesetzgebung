import os
import locale
from dotenv import load_dotenv
from gesetzgebung.flask_file import app
from gesetzgebung.database import db
from gesetzgebung.es_file import *
from gesetzgebung.models import *
from sqlalchemy import text

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))

locale.setlocale(locale.LC_TIME, "de_DE.utf8")

DATABASE_URI = os.environ.get("DATABASE_URL", "").replace(
    "postgres://", "postgresql://"
) or os.environ.get("LOCAL_DATABASE_URL", "")
DEBUG = os.environ.get("ENV_FLAG", "") == "development"

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {  # TODO: remove this if it causes problems
    "pool_size": 5,
    "max_overflow": 10,
    "pool_recycle": 1500,  # Recycle connections after 1 hour
    "pool_pre_ping": True,  # Test connections before use
}
app.config["DEBUG"] = DEBUG

db.init_app(app)


with app.app_context():
    db.session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    db.create_all()
    db.session.commit()
