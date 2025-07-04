from flask import Flask
from pathlib import Path

# Get the path to the main gesetzgebung directory (parent of infrastructure)
basedir = Path(__file__).parent.parent

app = Flask(__name__.split(".")[0], root_path=str(basedir))
