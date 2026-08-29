"""Rebuild omw.db from scratch with the full seed data set.

Drops the SQLite database and recreates it: the schema, the original resources
(shelters, pantries, free wifi) with their seed statuses, and the eight
fully-populated inner-Sydney food banks - opening hours for every day, wifi and
bathroom flags, and a starting fill level for perishables, non-perishables and
toiletries, each timestamped a different number of minutes ago so confidence
varies between them.

Re-runnable with a single command:

    venv/bin/python seed.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "omw.db"


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Dropped {DB_PATH.name}.")

    # init_db() runs on import; call it again explicitly for clarity. It
    # recreates the schema and inserts every seed row into the fresh database.
    import app

    app.init_db()

    db = sqlite3.connect(DB_PATH)
    total = db.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
    foodbanks = db.execute(
        "SELECT COUNT(*) FROM resources WHERE perishables_pct IS NOT NULL"
    ).fetchone()[0]
    db.close()

    print(f"Recreated {DB_PATH.name}: {total} resources, {foodbanks} food banks.")


if __name__ == "__main__":
    main()
