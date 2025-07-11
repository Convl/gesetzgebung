# Apply numpy compatibility patch before any imports
import numpy as np

np.float_ = np.float64

from gesetzgebung.infrastructure.config import app, db, es
from gesetzgebung.webapp import routes
