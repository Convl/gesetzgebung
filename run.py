from gesetzgebung import app

if __name__ == "__main__":
    if app.config["DEBUG"]:
        app.run(debug=True, host="0.0.0.0", port=5000)
    else:
        app.run(debug=False)
