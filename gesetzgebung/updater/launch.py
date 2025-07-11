# np.float_ deprecated in numpy>=2, but required by elasticsearch7
import numpy as np

np.float_ = np.float64

import datetime
from pathlib import Path

from dotenv import load_dotenv

from gesetzgebung.infrastructure.config import app
from gesetzgebung.infrastructure.models import (
    is_update_active,
    set_update_active,
)
from gesetzgebung.updater.logger import logger
from gesetzgebung.updater.update_laws import update_laws
from gesetzgebung.updater.update_news import update_news_update_candidates


def launch():
    basedir = Path(__file__).parent.parent
    load_dotenv(basedir / ".env")

    with app.app_context():
        if is_update_active():
            logger.critical(
                f"Script already in progress. Immediately terminating new process at {datetime.datetime.now()}.",
                subject="Daily update launched while still in progress.",
            )

        set_update_active(True)

        try:
            update_laws()
            update_news_update_candidates()
        except Exception as e:
            logger.critical(f"Unknown exception: {e}", subject="Unknown exception")

        set_update_active(False)


if __name__ == "__main__":
    launch()
