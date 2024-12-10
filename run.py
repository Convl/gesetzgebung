from gesetzgebung import app
import os

if __name__ == '__main__':
    if os.environ.get("ENV_FLAG", "") == "development":
        app.run(debug=True)
    else:
        app.run()