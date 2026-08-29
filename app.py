import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request

import capacity
import confidence
import openhours
import routing
import vision

load_dotenv()
ORS_API_KEY = os.environ.get("ORS_API_KEY")

DB_PATH = Path(__file__).parent / "omw.db"

# Every opening hour in the seed is an Australia/Sydney wall-clock time. The
# /api/resources handler compares them against the current Sydney time, never
# UTC, so is_open_now reflects what a person standing in Sydney would see.
SYDNEY_TZ = ZoneInfo("Australia/Sydney")

_MON_FRI = ("mon", "tue", "wed", "thu", "fri")
_ALL_DAYS = _MON_FRI + ("sat", "sun")


def _hours(weekday, sat, sun):
    """Build a 7-day opening-hours dict from Mon-Fri hours plus explicit
    Saturday and Sunday hours. Each argument is a list of ["HH:MM", "HH:MM"]
    open/close pairs (an empty list means closed that day)."""
    days = {day: [pair[:] for pair in weekday] for day in _MON_FRI}
    days["sat"] = [pair[:] for pair in sat]
    days["sun"] = [pair[:] for pair in sun]
    return days


def _every_day(intervals):
    """Opening hours identical on all seven days."""
    return {day: [pair[:] for pair in intervals] for day in _ALL_DAYS}


# Round-the-clock crisis services and always-on public wifi.
_ALWAYS_OPEN = _every_day([["00:00", "24:00"]])

# Shelters and free-wifi points. Food banks are seeded separately, below. Every
# entry carries a full week of Sydney-local opening hours and an initial status
# report as (status, minutes_since_reported) so the map shows a mix of colours
# out of the box; free-wifi points have hours and a status only - no food
# capacity or facility fields.
SEED_RESOURCES = [
    {
        "name": "Wayside Chapel Shelter", "kind": "shelter",
        "lat": -33.8769, "lng": 151.2223,
        "hours": _ALWAYS_OPEN, "free_wifi": True, "bathroom": True,
        "status": ("available", 20),
    },
    {
        "name": "Matthew Talbot Hostel", "kind": "shelter",
        "lat": -33.8710, "lng": 151.2170,
        "hours": _ALWAYS_OPEN, "free_wifi": False, "bathroom": True,
        "status": ("available", 95),
    },
    {
        "name": "St Vincent's Night Refuge", "kind": "shelter",
        "lat": -33.8794, "lng": 151.2160,
        "hours": _every_day([["00:00", "09:00"], ["17:00", "24:00"]]),
        "free_wifi": False, "bathroom": True,
        "status": ("unavailable", 40),
    },
    {
        "name": "Town Hall Square Free WiFi", "kind": "wifi",
        "lat": -33.8731, "lng": 151.2065,
        "hours": _ALWAYS_OPEN,
        "status": ("available", 5),
    },
    {
        "name": "Customs House Library WiFi", "kind": "wifi",
        "lat": -33.8614, "lng": 151.2100,
        "hours": _hours(
            [["10:00", "19:00"]], [["11:00", "16:00"]], [["11:00", "16:00"]]
        ),
        "status": ("unknown", None),
    },
]

# Inner-Sydney food banks, all kind "pantry". Each carries opening hours for
# every weekday (a list of [open, close] "HH:MM" pairs; an empty list means
# closed that day), two facility flags, and a starting fill level per stock
# category as (percent, minutes_since_reported) - turned into a timestamp at
# seed time. The category ages are staggered across the last few hours so
# confidence differs between categories and between food banks. An optional
# "status" as (status, minutes_since_reported) seeds a colour on the map;
# without it the pantry starts "unknown".
SEED_FOODBANKS = [
    {
        "name": "OzHarvest Waterloo",
        "lat": -33.9018, "lng": 151.2050,
        "hours": _hours(
            [["09:00", "15:00"]], [["09:00", "12:00"]], [["10:00", "13:00"]]
        ),
        "free_wifi": True, "bathroom": True,
        "perishables": (45, 20),
        "non_perishables": (78, 210),
        "toiletries": (62, 95),
    },
    {
        "name": "Addison Road Food Pantry",
        "lat": -33.9098, "lng": 151.1585,
        "hours": _hours(
            [["10:00", "13:00"]], [["08:00", "13:00"]], [["10:00", "13:00"]]
        ),
        "free_wifi": False, "bathroom": True,
        "perishables": (33, 140),
        "non_perishables": (60, 270),
        "toiletries": (44, 175),
    },
    {
        "name": "Exodus Foundation Loaves & Fishes",
        "lat": -33.8885, "lng": 151.1250,
        "hours": _hours(
            [["08:00", "11:30"], ["12:00", "14:00"]],
            [["08:00", "11:00"]], [["08:00", "11:00"]],
        ),
        "free_wifi": False, "bathroom": True,
        "perishables": (57, 15),
        "non_perishables": (82, 130),
        "toiletries": (66, 240),
    },
    {
        "name": "Vinnies Woolloomooloo Pantry",
        "lat": -33.8703, "lng": 151.2192,
        "hours": _hours(
            [["09:30", "13:00"]], [["09:30", "12:00"]], [["10:00", "12:00"]]
        ),
        "free_wifi": True, "bathroom": True,
        "perishables": (40, 55),
        "non_perishables": (68, 190),
        "toiletries": (28, 300),
    },
    {
        "name": "Salvos Streetlevel Surry Hills",
        "lat": -33.8860, "lng": 151.2110,
        "hours": _hours(
            [["10:00", "16:00"]], [["10:00", "14:00"]], [["12:00", "15:00"]]
        ),
        "free_wifi": True, "bathroom": True,
        "perishables": (36, 40),
        "non_perishables": (72, 165),
        "toiletries": (50, 110),
    },
    {
        "name": "Newtown Neighbourhood Centre Food Hub",
        "lat": -33.8975, "lng": 151.1795,
        "hours": _hours(
            [["11:00", "14:00"]], [["10:00", "13:00"]], [["10:00", "13:00"]]
        ),
        "free_wifi": True, "bathroom": False,
        "perishables": (29, 80),
        "non_perishables": (53, 250),
        "toiletries": (24, 200),
    },
    {
        "name": "The Factory Community Pantry",
        "lat": -33.9055, "lng": 151.2085,
        "hours": _hours(
            [["09:00", "12:00"]], [["09:00", "12:00"]], [["09:00", "12:00"]]
        ),
        "free_wifi": False, "bathroom": True,
        "perishables": (49, 25),
        "non_perishables": (63, 155),
        "toiletries": (47, 130),
    },
    {
        "name": "Kings Cross Community Pantry",
        "lat": -33.8740, "lng": 151.2235,
        "hours": _hours(
            [["08:00", "13:00"]], [["08:00", "13:00"]], [["08:00", "13:00"]]
        ),
        "free_wifi": True, "bathroom": True,
        "perishables": (61, 10),
        "non_perishables": (88, 65),
        "toiletries": (72, 50),
    },
    {
        "name": "OzHarvest Market Pantry",
        "lat": -33.8850, "lng": 151.1990,
        "hours": _hours(
            [["10:00", "16:00"]], [["10:00", "15:00"]], []
        ),
        "free_wifi": True, "bathroom": True,
        "perishables": (52, 30),
        "non_perishables": (70, 180),
        "toiletries": (58, 120),
        "status": ("available", 8),
    },
    {
        "name": "Redfern Community Pantry",
        "lat": -33.8930, "lng": 151.2040,
        "hours": _hours(
            [["09:00", "13:00"]], [["09:00", "13:00"]], []
        ),
        "free_wifi": False, "bathroom": True,
        "perishables": (38, 150),
        "non_perishables": (64, 240),
        "toiletries": (41, 90),
    },
    {
        "name": "Foodbank City Pop-up",
        "lat": -33.8790, "lng": 151.2050,
        "hours": _hours(
            [["11:00", "18:00"]], [["11:00", "17:00"]], [["12:00", "16:00"]]
        ),
        "free_wifi": True, "bathroom": False,
        "perishables": (44, 45),
        "non_perishables": (58, 200),
        "toiletries": (36, 160),
        "status": ("unavailable", 180),
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

    # One row per submitted "Update info" report: the raw slider values a person
    # entered, before they are blended into the resource's running estimate.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS capacity_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id INTEGER NOT NULL,
            perishables REAL NOT NULL,
            non_perishables REAL NOT NULL,
            toiletries REAL NOT NULL,
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

    now = datetime.now(timezone.utc)

    count = db.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
    if count == 0:
        db.executemany(
            """
            INSERT INTO resources (name, kind, lat, lng, hours, free_wifi, bathroom)
            VALUES (:name, :kind, :lat, :lng, :hours, :free_wifi, :bathroom)
            """,
            [
                {
                    "name": r["name"], "kind": r["kind"],
                    "lat": r["lat"], "lng": r["lng"],
                    "hours": json.dumps(r["hours"]),
                    "free_wifi": int(r.get("free_wifi", False)),
                    "bathroom": int(r.get("bathroom", False)),
                }
                for r in SEED_RESOURCES
            ],
        )

    # Give any resource that has never had a report an initial status.
    for res in SEED_RESOURCES:
        status, minutes_ago = res["status"]
        row = db.execute(
            "SELECT id, last_report FROM resources WHERE name = ?", (res["name"],)
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
        status, status_minutes = fb.get("status", ("unknown", None))
        last_report = (
            None
            if status_minutes is None
            else (now - timedelta(minutes=status_minutes)).isoformat()
        )
        db.execute(
            """
            INSERT INTO resources (
                name, kind, lat, lng, status, last_report,
                hours, free_wifi, bathroom,
                perishables_pct, perishables_reported,
                non_perishables_pct, non_perishables_reported,
                toiletries_pct, toiletries_reported
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fb["name"], "pantry", fb["lat"], fb["lng"], status, last_report,
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


@app.route("/api/route")
def route():
    """Foot-walking route between two points, from OpenRouteService.

    Query: from_lat, from_lng, to_lat, to_lng. Returns the route geometry as
    GeoJSON plus distance_m and duration_s. On any ORS error or timeout, falls
    back to a straight line and a haversine estimate with is_estimate true.
    """
    try:
        coords = [
            float(request.args[name])
            for name in ("from_lat", "from_lng", "to_lat", "to_lng")
        ]
    except (KeyError, ValueError):
        return jsonify({"error": "from_lat, from_lng, to_lat, to_lng required"}), 400
    return jsonify(routing.get_route(*coords, ORS_API_KEY))


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
    # is_open_now is reckoned against the current Sydney time, never UTC.
    now_local = datetime.now(SYDNEY_TZ)
    result = []
    for row in rows:
        item = dict(row)
        item["confidence"] = report_confidence(
            item["kind"], item["status"], item["last_report"], now
        )
        item["hours"] = json.loads(item["hours"]) if item["hours"] else None
        item["is_open_now"] = openhours.is_open(item["hours"], now_local)

        if item["kind"] == "wifi":
            # Free-wifi points have their own shape: hours and a status only, no
            # food-capacity or facility fields.
            for key in (
                "free_wifi", "bathroom",
                "perishables_pct", "perishables_reported",
                "non_perishables_pct", "non_perishables_reported",
                "toiletries_pct", "toiletries_reported",
            ):
                item.pop(key, None)
        else:
            item["free_wifi"] = bool(item["free_wifi"])
            item["bathroom"] = bool(item["bathroom"])
            item["overall_capacity"] = capacity.overall_capacity(
                item["perishables_pct"],
                item["non_perishables_pct"],
                item["toiletries_pct"],
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


CAPACITY_CATEGORIES = ("perishables", "non_perishables", "toiletries")


@app.route("/api/resources/<int:resource_id>/capacity", methods=["POST"])
def capacity_report(resource_id):
    """Fold a fresh per-category fill-level report into the running estimate.

    Body: {"perishables": 0-100, "non_perishables": 0-100, "toiletries": 0-100}.
    Each new value is blended with the stored estimate, weighting the old value by
    its current confidence (confidence.py), so a stale estimate is almost fully
    replaced and a fresh one only shifts halfway.
    """
    data = request.get_json(silent=True) or {}
    new_values = {}
    for cat in CAPACITY_CATEGORIES:
        value = data.get(cat)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return jsonify({"error": f"invalid {cat}"}), 400
        if not 0 <= value <= 100:
            return jsonify({"error": f"{cat} out of range"}), 400
        new_values[cat] = float(value)

    db = get_db()
    row = db.execute(
        """
        SELECT kind,
               perishables_pct, perishables_reported,
               non_perishables_pct, non_perishables_reported,
               toiletries_pct, toiletries_reported
        FROM resources WHERE id = ?
        """,
        (resource_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    blended = {}
    for cat in CAPACITY_CATEGORIES:
        old_value = row[f"{cat}_pct"]
        reported = row[f"{cat}_reported"]
        old_confidence = 0.0
        if old_value is not None and reported:
            reported_at = datetime.fromisoformat(reported)
            if reported_at.tzinfo is None:
                reported_at = reported_at.replace(tzinfo=timezone.utc)
            age = (now - reported_at).total_seconds()
            old_confidence = confidence.confidence(row["kind"], age)
        blended[cat] = round(
            confidence.blend(old_value, old_confidence, new_values[cat]), 1
        )

    db.execute(
        """
        INSERT INTO capacity_reports
            (resource_id, perishables, non_perishables, toiletries, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            resource_id,
            new_values["perishables"],
            new_values["non_perishables"],
            new_values["toiletries"],
            now_iso,
        ),
    )
    db.execute(
        """
        UPDATE resources SET
            perishables_pct = ?, perishables_reported = ?,
            non_perishables_pct = ?, non_perishables_reported = ?,
            toiletries_pct = ?, toiletries_reported = ?
        WHERE id = ?
        """,
        (
            blended["perishables"], now_iso,
            blended["non_perishables"], now_iso,
            blended["toiletries"], now_iso,
            resource_id,
        ),
    )
    db.commit()

    response = {"overall_capacity": capacity.overall_capacity(
        blended["perishables"], blended["non_perishables"], blended["toiletries"]
    )}
    for cat in CAPACITY_CATEGORIES:
        response[f"{cat}_pct"] = blended[cat]
        response[f"{cat}_reported"] = now_iso
    return jsonify(response)


# The vision call bounds itself to vision.TIMEOUT_MS (12s). Run it off the request
# thread and give the outer wait a slightly longer deadline, so the wrapper never
# cuts the thread off mid-call.
ESTIMATE_TIMEOUT_SECONDS = 14
_vision_pool = ThreadPoolExecutor(max_workers=2)
MAX_IMAGE_BYTES = 10 * 1024 * 1024


@app.route("/api/estimate", methods=["POST"])
def estimate():
    """Guess per-category shelf fullness from an uploaded photo.

    Body: multipart/form-data with an "image" file. Returns
    {"perishables_pct", "non_perishables_pct", "toiletries_pct", "confidence"}
    on success. Any failure (no key, bad image, timeout, API error) returns 503
    with {"error": "unavailable"} -- the frontend treats that as "fall back to
    the manual sliders" and shows nothing.
    """
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        return jsonify({"error": "no image"}), 400

    image_bytes = upload.read()
    if not image_bytes:
        return jsonify({"error": "empty image"}), 400
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return jsonify({"error": "image too large"}), 413

    future = _vision_pool.submit(vision.estimate_capacity, image_bytes)
    try:
        result = future.result(timeout=ESTIMATE_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        future.cancel()
        app.logger.exception("photo capacity estimate timed out")
        return jsonify({"error": "unavailable"}), 503
    except Exception:
        app.logger.exception("photo capacity estimate failed")
        return jsonify({"error": "unavailable"}), 503

    return jsonify(result)


init_db()

if __name__ == "__main__":
    app.run(port=5001, debug=True)
