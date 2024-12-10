from gesetzgebung.config import app, db, es, ES_LAWS_INDEX, scheduler
from gesetzgebung.models import get_all_laws


# with app.app_context():
    # db.create_all() # TODO remove this before production

from gesetzgebung import routes

