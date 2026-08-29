import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, render_template, request

import capacity
import confidence
import openhours

DB_PATH = Path(__file__).parent / "omw.db"

# Opening hours and is_open_now are reckoned in the resources' local time.
SYDNEY_TZ = ZoneInfo("Australia/Sydney")

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

# Eight inner-Sydney food banks, seeded alongside SEED_RESOURCES (all kind
# "pantry"). Each carries opening hours (per weekday, a list of [open, close]
# "HH:MM" pairs; a missing day means closed), two facility flags, and a starting
# fill level per stock category as (percent, minutes_since_reported) - turned
# into a timestamp at seed time.
_MON_FRI = ("mon", "tue", "wed", "thu", "fri")

SEED_FOODBANKS = [
    {
        "name": "OzHarvest Waterloo",
        "lat": -33.9018, "lng": 151.2050,
        "hours": {d: [["09:00", "15:00"]] for d in _MON_FRI},
        "free_wifi": True, "bathroom": True,
        "perishables": (48, 25),
        "non_perishables": (74, 200),
        "toiletries": (60, 120),
    },
    {
        "name": "Addison Road Food Pantry",
        "lat": -33.9098, "lng": 151.1585,
        "hours": {"wed": [["10:00", "13:00"]], "sat": [["10:00", "13:00"]]},
        "free_wifi": False, "bathroom": True,
        "perishables": (35, 60),
        "non_perishables": (58, 600),
        "toiletries": (40, 300),
    },
    {
        "name": "Exodus Foundation Loaves & Fishes",
        "lat": -33.8885, "lng": 151.1250,
        "hours": {d: [["08:00", "11:30"], ["12:00", "14:00"]] for d in _MON_FRI},
        "free_wifi": False, "bathroom": True,
        "perishables": (55, 15),
        "non_perishables": (80, 90),
        "toiletries": (65, 240),
    },
    {
        "name": "Vinnies Woolloomooloo Pantry",
        "lat": -33.8703, "lng": 151.2192,
        "hours": {d: [["09:30", "13:00"]] for d in ("mon", "tue", "thu", "fri")},
        "free_wifi": True, "bathroom": True,
        "perishables": (42, 45),
        "non_perishables": (66, 420),
        "toiletries": (30, 1200),
    },
    {
        "name": "Salvos Streetlevel Surry Hills",
        "lat": -33.8860, "lng": 151.2110,
        "hours": {d: [["10:00", "16:00"]] for d in _MON_FRI},
        "free_wifi": True, "bathroom": True,
        "perishables": (38, 35),
        "non_perishables": (70, 180),
        "toiletries": (52, 150),
    },
    {
        "name": "Newtown Neighbourhood Centre Food Hub",
        "lat": -33.8975, "lng": 151.1795,
        "hours": {"tue": [["11:00", "14:00"]], "thu": [["11:00", "14:00"]]},
        "free_wifi": True, "bathroom": False,
        "perishables": (30, 75),
        "non_perishables": (55, 900),
        "toiletries": (25, 540),
    },
    {
        "name": "The Factory Community Pantry",
        "lat": -33.9055, "lng": 151.2085,
        "hours": {d: [["09:00", "12:00"]] for d in ("mon", "tue", "thu", "fri")},
        "free_wifi": False, "bathroom": True,
        "perishables": (50, 20),
        "non_perishables": (62, 360),
        "toiletries": (48, 200),
    },
    {
        "name": "Kings Cross Community Pantry",
        "lat": -33.8740, "lng": 151.2235,
        "hours": {
            d: [["08:00", "13:00"]]
            for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        },
        "free_wifi": True, "bathroom": True,
        "perishables": (58, 10),
        "non_perishables": (85, 60),
        "toiletries": (70, 45),
    },
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
            lng REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'unknown',
            last_report TEXT,
            hours TEXT,
            free_wifi INTEGER NOT NULL DEFAULT 0,
            bathroom INTEGER NOT NULL DEFAULT 0,
            perishables_pct REAL,
            perishables_reported TEXT,
            non_perishables_pct REAL,
            non_perishables_reported TEXT,
            toiletries_pct REAL,
            toiletries_reported TEXT
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

    for col, decl in (
        ("hours", "TEXT"),
        ("free_wifi", "INTEGER NOT NULL DEFAULT 0"),
        ("bathroom", "INTEGER NOT NULL DEFAULT 0"),
        ("perishables_pct", "REAL"),
        ("perishables_reported", "TEXT"),
        ("non_perishables_pct", "REAL"),
        ("non_perishables_reported", "TEXT"),
        ("toiletries_pct", "REAL"),
        ("toiletries_reported", "TEXT"),
    ):
        if col not in columns:
            db.execute(f"ALTER TABLE resources ADD COLUMN {col} {decl}")

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

    # Add any seed food bank not already present. Additive and idempotent, so it
    # is safe to run on every startup, on a fresh or an existing database.
    for fb in SEED_FOODBANKS:
        if db.execute(
            "SELECT 1 FROM resources WHERE name = ?", (fb["name"],)
        ).fetchone() is not None:
            continue
        pct = {cat: fb[cat][0] for cat in ("perishables", "non_perishables", "toiletries")}
        reported = {
            cat: (now - timedelta(minutes=fb[cat][1])).isoformat()
            for cat in ("perishables", "non_perishables", "toiletries")
        }
        db.execute(
            """
            INSERT INTO resources (
                name, kind, lat, lng, hours, free_wifi, bathroom,
                perishables_pct, perishables_reported,
                non_perishables_pct, non_perishables_reported,
                toiletries_pct, toiletries_reported
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fb["name"], "pantry", fb["lat"], fb["lng"],
                json.dumps(fb["hours"]),
                int(fb["free_wifi"]), int(fb["bathroom"]),
                pct["perishables"], reported["perishables"],
                pct["non_perishables"], reported["non_perishables"],
                pct["toiletries"], reported["toiletries"],
            ),
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
        """
        SELECT id, name, kind, lat, lng, status, last_report,
               hours, free_wifi, bathroom,
               perishables_pct, perishables_reported,
               non_perishables_pct, non_perishables_reported,
               toiletries_pct, toiletries_reported
        FROM resources
        """
    ).fetchall()
    now = datetime.now(timezone.utc)
    now_local = datetime.now(SYDNEY_TZ)
    result = []
    for row in rows:
        item = dict(row)
        item["confidence"] = report_confidence(
            item["kind"], item["status"], item["last_report"], now
        )
        item["hours"] = json.loads(item["hours"]) if item["hours"] else None
        item["free_wifi"] = bool(item["free_wifi"])
        item["bathroom"] = bool(item["bathroom"])
        item["overall_capacity"] = capacity.overall_capacity(
            item["perishables_pct"],
            item["non_perishables_pct"],
            item["toiletries_pct"],
        )
        item["is_open_now"] = openhours.is_open(item["hours"], now_local)
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
