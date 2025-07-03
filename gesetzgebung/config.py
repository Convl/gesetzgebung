import locale
import os

from dotenv import load_dotenv
from flask_migrate import Migrate
from sqlalchemy import text

from gesetzgebung.database import db
from gesetzgebung.es_file import *
from gesetzgebung.flask_file import app
from gesetzgebung.models import *

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))

locale.setlocale(locale.LC_TIME, "de_DE.utf8")

DATABASE_URI = os.environ.get("DATABASE_URL", "").replace(
    "postgres://", "postgresql://"
) or os.environ.get("LOCAL_DATABASE_URL", "")
DEV = os.environ.get("ENV_FLAG", "") == "development"

app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "")
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {  # TODO: remove this if it causes problems
    "pool_size": 5,
    "max_overflow": 10,
    "pool_recycle": 1500,
    "pool_pre_ping": True,
}

migrate = Migrate(app, db)
db.init_app(app)


with app.app_context():
    if not DEV:
        db.session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    db.create_all()
    db.session.commit()
