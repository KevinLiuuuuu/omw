# OMW

A live status map for community food resources in inner Sydney. OMW shows nearby
food banks, shelters and free-wifi points on a map, colour-coded by how recently
someone confirmed the resource is actually usable right now.

## The problem

Directories like Ask Izzy will tell you that a food bank exists and when it is
open. They will not tell you whether it has anything on the shelves today. Stock
runs out mid-morning, pop-ups move, a shelter fills its beds by 6pm. Someone
acting on a stale listing can lose an hour crossing the city to find an empty
room.

OMW crowdsources current status. Anyone at a resource can report what they see:
"it's available", "it's out", or a rough fill level per stock category. Everyone
else sees that report age in real time, so they can judge for themselves whether
it is still worth the trip.

## What it does

- A full-viewport map of resources, with a sidebar list sorted by distance from
  the user.
- Coloured markers for status (available / unavailable / unknown), faded by
  confidence as the last report gets older.
- A detail panel per resource: opening hours (evaluated against the current
  Sydney wall-clock time), wifi and bathroom flags, and for food banks a stock
  breakdown across perishables, non-perishables and toiletries plus a blended
  overall figure.
- Reporting buttons and a fill-level update form that feed straight back into the
  map.
- Real walking routes and walk times from the user to a resource, via
  OpenRouteService, with a straight-line haversine estimate as a fallback.

## How the confidence model works

Every status report is fully trusted (confidence `1.0`) the instant it is made,
then decays exponentially with age. How fast it decays depends on the resource
type, because different resources go stale at different rates. Each type has a
**half-life** — the age at which confidence has dropped to `0.5`:

| Resource type | Half-life |
|---------------|-----------|
| Shelter       | 1 hour    |
| Pantry        | 2 hours   |
| Free wifi     | 7 days    |

An unknown type falls back to the shelter half-life. A resource with no report,
or an explicitly `unknown` status, has confidence `0.0`. See `confidence.py`.

### Blending new reports with old estimates

Food-bank fill levels are not overwritten by each new report. A fresh report is
folded into the stored estimate, weighting the old value by *its own current
confidence*:

```
blended = (old_value * old_confidence + new_value) / (old_confidence + 1)
```

So a stale estimate (confidence near `0`) is almost entirely replaced by the new
report, while a still-fresh one (confidence near `1`) only shifts halfway toward
it — two recent observers who disagree meet in the middle rather than fighting
over the marker. With no prior estimate the new report stands alone. This runs
per stock category, each category carrying its own timestamp and therefore its
own confidence. See `blend()` in `confidence.py`.

The overall capacity shown for a food bank is a weighted average of the three
category percentages (equal thirds for now, but kept tunable), with unreported
categories dropped and the weights renormalised across the rest. See
`capacity.py`.

## Stack

- Flask backend, Python, SQLite storage (`omw.db`)
- Vanilla JS frontend, Tailwind via CDN, no build step
- Leaflet with CARTO Voyager basemap tiles
- OpenRouteService for walking directions
- The pure logic modules (`confidence.py`, `capacity.py`, `openhours.py`,
  `routing.py`) are standard-library only and unit-tested under `tests/`
- Runs on port 5001

## Running it locally

```
python -m venv venv
venv/bin/pip install -r requirements.txt
```

Create a `.env` file in the project root with the following key:

- `ORS_API_KEY` — an OpenRouteService API key, for walking routes. Without it the
  app still runs; routes fall back to straight-line estimates.

Seed the database (drops and rebuilds `omw.db` with all resources and food-bank
stock data):

```
venv/bin/python seed.py
```

Then start the app:

```
venv/bin/python app.py
```

and open http://localhost:5001. `app.py` also creates the schema and inserts any
missing seed rows on startup, so the seed script is only needed for a clean
rebuild.

Run the tests with:

```
venv/bin/python -m unittest discover tests
```
