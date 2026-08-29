# OMW
Live status map for community resources. Users see nearby shelters, pantries and free wifi on a map, with how recently someone confirmed the resource is actually available.

## Stack
- Flask backend, Python
- Vanilla JS frontend, Tailwind via CDN, no build step
- Leaflet + OpenStreetMap tiles for the map
- SQLite for storage
- Runs on port 5001

## Rules
- Keep it simple. No React, no bundlers, no npm.
- Ask before adding any dependency.
- Do not refactor code you were not asked to touch.
- One feature at a time. Do not build ahead.
- Small commits after each working change.
