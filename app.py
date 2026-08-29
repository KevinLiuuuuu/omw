import sqlite3
from datetime import datetime, timedelta, timezone
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

# Initial status reports for the seeded resources, so the map shows a mix of
# colours out of the box. name -> (status, minutes since last report).
SEED_STATUS = {
    "Wayside Chapel Shelter": ("available", 20),
    "Matthew Talbot Hostel": ("available", 95),
    "St Vincent's Night Refuge": ("unavailable", 40),
    "OzHarvest Market Pantry": ("available", 8),
    "Redfern Community Pantry": ("unknown", None),
    "Foodbank City Pop-up": ("unavailable", 180),
    "Town Hall Square Free WiFi": ("available", 5),
    "Customs House Library WiFi": ("unknown", None),
}

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
            lng REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'unknown',
            last_report TEXT
        )
        """
    )

    columns = {row[1] for row in db.execute("PRAGMA table_info(resources)")}
    if "status" not in columns:
        db.execute(
            "ALTER TABLE resources ADD COLUMN status TEXT NOT NULL DEFAULT 'unknown'"
        )
    if "last_report" not in columns:
        db.execute("ALTER TABLE resources ADD COLUMN last_report TEXT")

    count = db.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
    if count == 0:
        db.executemany(
            "INSERT INTO resources (name, kind, lat, lng) VALUES (?, ?, ?, ?)",
            SEED_RESOURCES,
        )

    # Give any resource that has never had a report an initial status.
    now = datetime.now(timezone.utc)
    for name, (status, minutes_ago) in SEED_STATUS.items():
        row = db.execute(
            "SELECT id, last_report FROM resources WHERE name = ?", (name,)
        ).fetchone()
        if row is None or row[1] is not None:
            continue
        reported_at = (
            None
            if minutes_ago is None
            else (now - timedelta(minutes=minutes_ago)).isoformat()
        )
        db.execute(
            "UPDATE resources SET status = ?, last_report = ? WHERE id = ?",
            (status, reported_at, row[0]),
        )

    db.commit()
    db.close()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/resources")
def resources():
    rows = get_db().execute(
        "SELECT id, name, kind, lat, lng, status, last_report FROM resources"
    ).fetchall()
    return jsonify([dict(row) for row in rows])


init_db()

if __name__ == "__main__":
    app.run(port=5001, debug=True)
