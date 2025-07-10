# np.float_ deprecated in numpy>=2, but required by elasticsearch7
import numpy as np

np.float_ = np.float64
