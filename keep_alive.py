from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Doctor Jung is alive!"

def run():
    # Render usa la porta 10000 di default o quella nella var PORT
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()