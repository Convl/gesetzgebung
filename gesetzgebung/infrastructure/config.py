import locale
import os
from pathlib import Path

# Hack to ensure backwards compatibility with elasticsearch7.
# Should not be needed if numpy<2 moved down in requirements or requirements locked.
# import numpy as np
# np.float_ = np.float64
from dotenv import load_dotenv
from elasticsearch7 import Elasticsearch
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

# Load environment variables
basedir = Path(__file__).parent.parent
load_dotenv(basedir / ".env")

DEV = os.environ.get("ENV_FLAG", "") == "development"
DATABASE_URI = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://") or os.environ.get(
    "LOCAL_DATABASE_URL", ""
)
ES_HOST = os.environ.get("ES_HOST") or os.environ.get("LOCAL_ES_HOST")
ES_LAWS_INDEX = os.environ.get("ES_LAWS_INDEX") or os.environ.get("LOCAL_ES_LAWS_INDEX")
ES_INDEX_BODY = {
    "settings": {
        "index": {"max_ngram_diff": 18},
        "analysis": {
            "analyzer": {
                "ngram_analyzer": {"tokenizer": "ngram_tokenizer", "filter": ["lowercase"]},
                "ngram_search": {"tokenizer": "lowercase"},
            },
            "tokenizer": {
                "ngram_tokenizer": {"type": "ngram", "min_gram": 3, "max_gram": 20, "token_chars": ["letter", "digit"]}
            },
        },
    },
    "mappings": {
        "properties": {
            "titel": {"type": "text", "analyzer": "ngram_analyzer", "search_analyzer": "ngram_search"},
            "abstract": {"type": "text", "analyzer": "ngram_analyzer", "search_analyzer": "ngram_search"},
        }
    },
}

# Set locale
locale.setlocale(locale.LC_TIME, "de_DE.utf8")

# Flask setup / config
app = Flask(__name__.split(".")[0], root_path=str(basedir))
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "")
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_size": 5,
    "max_overflow": 10,
    "pool_recycle": 1500,
    "pool_pre_ping": True,
}

# Database setup / config
db = SQLAlchemy()
db.init_app(app)

# Alembic setup
migrate = Migrate(app, db)

# Elastissearch setup / config
es = Elasticsearch(ES_HOST, verify_certs=False, headers={"x-elastic-product": "Elasticsearch"})
if ES_LAWS_INDEX and not es.indices.exists(index=ES_LAWS_INDEX):
    es.indices.create(index=ES_LAWS_INDEX, body=ES_INDEX_BODY)

# Create database tables / addons if not already present
with app.app_context():
    if not DEV:
        db.session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    db.create_all()
    db.session.commit()

from gesetzgebung.infrastructure.models import *
