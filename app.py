import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request

import confidence

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

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
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


def report_confidence(kind, status, last_report, now):
    """Confidence in a resource's current status, in [0.0, 1.0].

    Zero when there is no report or the status is unknown; otherwise the report's
    age is decayed at the rate for its kind (see confidence.py).
    """
    if status == "unknown" or not last_report:
        return 0.0
    reported_at = datetime.fromisoformat(last_report)
    if reported_at.tzinfo is None:
        reported_at = reported_at.replace(tzinfo=timezone.utc)
    age = (now - reported_at).total_seconds()
    return round(confidence.confidence(kind, age), 3)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/resources")
def resources():
    rows = get_db().execute(
        "SELECT id, name, kind, lat, lng, status, last_report FROM resources"
    ).fetchall()
    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        item = dict(row)
        item["confidence"] = report_confidence(
            item["kind"], item["status"], item["last_report"], now
        )
        result.append(item)
    return jsonify(result)


@app.route("/api/resources/<int:resource_id>/report", methods=["POST"])
def report(resource_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("available", "unavailable"):
        return jsonify({"error": "invalid status"}), 400

    db = get_db()
    if db.execute(
        "SELECT 1 FROM resources WHERE id = ?", (resource_id,)
    ).fetchone() is None:
        return jsonify({"error": "not found"}), 404

    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO reports (resource_id, status, created_at) VALUES (?, ?, ?)",
        (resource_id, status, now),
    )
    db.execute(
        "UPDATE resources SET status = ?, last_report = ? WHERE id = ?",
        (status, now, resource_id),
    )
    db.commit()
    return jsonify({"status": status, "last_report": now, "confidence": 1.0})


init_db()

if __name__ == "__main__":
    app.run(port=5001, debug=True)
