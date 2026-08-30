# OMW

OMW is a live status map for community food resources: it shows nearby food
banks, shelters and free-wifi points on a map, colour-coded by how recently
someone confirmed the resource is actually usable. Anyone standing at a resource
can report what they see, and everyone else sees that report age in real time so
they can judge whether it is still worth the trip.

## What it does

- Full-viewport Leaflet map with a sidebar list sorted by distance from the user.
- Markers coloured by status (available / unavailable / unknown) and faded as the
  last report loses confidence with age.
- A detail panel per resource: opening hours evaluated against the current Sydney
  wall-clock time, wifi and bathroom flags, and for food banks a per-category
  stock breakdown (perishables, non-perishables, toiletries) plus a blended
  overall figure.
- Report buttons and a fill-level form that feed straight back into the map, with
  an optional photo-based pre-fill for the sliders (see below).
- Walking routes and walk times via OpenRouteService, falling back to a
  straight-line haversine estimate when the key is missing or the request fails.

## Stack

- Flask backend, Python, SQLite storage (`omw.db`), on port 5001.
- Vanilla JS frontend, Tailwind via CDN, no build step.
- Leaflet with CARTO Voyager basemap tiles. The CARTO key is a client-side tile
  key, embedded in the tile URL in `templates/index.html`; there is no
  server-side map config.
- `confidence.py`, `capacity.py`, `openhours.py` and `routing.py` are pure,
  standard-library-only logic modules, unit-tested under `tests/`.

## Running it locally

```
python -m venv venv
venv/bin/pip install -r requirements.txt
```

Create a git-ignored `.env` in the project root:

- `ORS_API_KEY` — OpenRouteService key, used by `/api/route`. Without it, routes
  fall back to straight-line estimates.
- `GEMINI_API_KEY` — Google Gemini key, used by `/api/estimate` for the photo
  fill-level estimate. Without it, the "use a photo" path silently does nothing
  and the manual sliders work as before.

Seed the database (drops and rebuilds `omw.db` with all resources and food-bank
stock data), then start the app and open <http://localhost:5001>:

```
venv/bin/python seed.py
venv/bin/python app.py
```

`app.py` also creates the schema and inserts missing seed rows on startup, so the
seed script is only needed for a clean rebuild. Tests:
`venv/bin/python -m unittest discover tests`.

## The confidence model

Every status report is fully trusted (confidence `1.0`) the instant it is made,
then decays exponentially with age. How fast depends on the resource type,
because different resources go stale at different rates. Each type has a
**half-life** — the age at which confidence has dropped to `0.5`:

| Resource type | Half-life |
|---------------|-----------|
| Shelter       | 1 hour    |
| Pantry        | 2 hours   |
| Free wifi     | 7 days    |

An unknown type falls back to the shelter half-life (1 hour). A resource with no
report, or an explicitly `unknown` status, has confidence `0.0`. See
`confidence.py`.

Food-bank fill levels are not overwritten by each new report. A fresh report is
folded into the stored estimate, weighting the old value by its own confidence:

```
blended = (old_value * old_confidence + new_value) / (old_confidence + 1)
```

A stale estimate (confidence near `0`) is almost entirely replaced by the new
report; a fresh one (near `1`) only shifts halfway toward it; with no prior
estimate the new report stands alone. This runs per stock category, each carrying
its own timestamp and confidence. The overall capacity is a weighted average of
the three category percentages (equal thirds for now, kept tunable), with
unreported categories dropped and the weights renormalised. See `capacity.py`.

## The photo estimate

`/api/estimate` accepts up to 4 shelf photos as multipart `image` files, downsizes
them, and asks Gemini for a per-category fullness percentage plus a short
description of what is visible. It is a pre-fill convenience only: the frontend
treats anything but a `200` as "use the manual sliders", and the endpoint never
lets a failure through — missing key, bad image, timeout or API error all degrade
to the manual flow. A submitted description is stored with the capacity report
and shown in the detail panel.
