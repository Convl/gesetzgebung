from gesetzgebung.config import app, db, es
from gesetzgebung import routes
import os

# TODO: Separate daily_update out altogether. For now, this is a hack to make sure the webapp on heroku does not import it, but GitHub Actions does. Mental note: There also is a .slugignore file with daily_update in it.
if os.environ.get("IS_WEBAPP") not in {True, "true", "True"}:
    from gesetzgebung import daily_update

