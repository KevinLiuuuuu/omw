import sqlite3
from pathlib import Path

from flask import Flask, g, jsonify, render_template

DB_PATH = Path(__file__).parent / "omw.db"

SEED_RESOURCES = [
    ("Wayside Chapel Shelter", "shelter", -33.8769, 151.2223),
    ("Matthew Talbot Hostel", "shelter", -33.8710, 151.2170),
    ("St Vincent's Night Refuge", "shelter", -33.8794, 151.2160),
    ("OzHarvest Market Pantry", "pantry", -33.8850, 151.1990),
    ("Redfern Community Pantry", "pantry", -33.8930, 151.2040),
    ("Foodbank City Pop-up", "pantry", -33.8790, 151.2050),
    ("Town Hall Square Free WiFi", "wifi", -33.8731, 151.2065),
    ("Customs House Library WiFi", "wifi", -33.8614, 151.2100),
]

app = Flask(__name__)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL
        )
        """
    )
    count = db.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
    if count == 0:
        db.executemany(
            "INSERT INTO resources (name, kind, lat, lng) VALUES (?, ?, ?, ?)",
            SEED_RESOURCES,
        )
        db.commit()
    db.close()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/resources")
def resources():
    rows = get_db().execute(
        "SELECT id, name, kind, lat, lng FROM resources"
    ).fetchall()
    return jsonify([dict(row) for row in rows])


init_db()

if __name__ == "__main__":
    app.run(port=5001, debug=True)
