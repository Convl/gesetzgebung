import os
import locale
from dotenv import load_dotenv
from gesetzgebung.flask_file import app
from gesetzgebung.database import db
from gesetzgebung.es_file import *
from gesetzgebung.models import *
from sqlalchemy import text 

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

locale.setlocale(locale.LC_TIME, 'de_DE.utf8')

DATABASE_URI = os.environ.get("DATABASE_URL", '').replace('postgres://', 'postgresql://') or os.environ.get("LOCAL_DATABASE_URL", '')
DEBUG = os.environ.get("ENV_FLAG", "") == "development"

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['DEBUG'] = DEBUG

db.init_app(app)


with app.app_context():    
    db.create_all()

    # db.session.execute(text("""
    #     ALTER TABLE vorhaben 
    #     ADD COLUMN IF NOT EXISTS queries text[] DEFAULT '{}',
    #     ADD COLUMN IF NOT EXISTS queries_last_updated date DEFAULT '1900-01-01',
    #     ADD COLUMN IF NOT EXISTS query_update_counter integer DEFAULT 0;
    # """))
    # db.session.commit()
    
    