print("Loading run.py")
from gesetzgebung import app
print("App imported, routes:", [rule.rule for rule in app.url_map.iter_rules()])

if __name__ == "__main__":
    if app.config["DEBUG"]:
        app.run(debug=True, host="0.0.0.0", port=5000)
    else:
        app.run(debug=False)
