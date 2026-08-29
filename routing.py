"""Walking routes from the OpenRouteService directions API.

get_route() asks ORS for a foot-walking route between two points and returns the
geometry as GeoJSON plus the real distance (metres) and duration (seconds).
Successful responses are cached in memory, keyed by the four coordinates rounded
to 4 decimal places (~11 m). On any error or a timeout past ORS_TIMEOUT seconds
it falls back to a straight line and a haversine-based estimate, flagged with
is_estimate.

Pure-ish: no Flask, no database. The API key is passed in by the caller so this
module never touches the environment or .env.
"""

import math

import requests

ORS_URL = "https://api.openrouteservice.org/v2/directions/foot-walking/geojson"
ORS_TIMEOUT = 3  # seconds

# Fallback estimate: streets add ~40% over the straight line, walked at 5 km/h.
STREET_FACTOR = 1.4
WALK_SPEED_MS = 5 * 1000 / 3600

# Coordinate pair -> route dict. Only real ORS responses land here, so a
# transient outage doesn't pin an estimate in place.
_cache = {}


def _haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance between two points, in metres."""
    p = math.pi / 180
    a = (
        math.sin((lat2 - lat1) * p / 2) ** 2
        + math.cos(lat1 * p)
        * math.cos(lat2 * p)
        * math.sin((lng2 - lng1) * p / 2) ** 2
    )
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _estimate(from_lat, from_lng, to_lat, to_lng):
    distance = _haversine_m(from_lat, from_lng, to_lat, to_lng) * STREET_FACTOR
    return {
        "geometry": {
            "type": "LineString",
            "coordinates": [[from_lng, from_lat], [to_lng, to_lat]],
        },
        "distance_m": round(distance, 1),
        "duration_s": round(distance / WALK_SPEED_MS, 1),
        "is_estimate": True,
    }


def get_route(from_lat, from_lng, to_lat, to_lng, api_key):
    key = tuple(round(v, 4) for v in (from_lat, from_lng, to_lat, to_lng))
    if key in _cache:
        return _cache[key]

    route = None
    if api_key:
        try:
            resp = requests.post(
                ORS_URL,
                json={"coordinates": [[from_lng, from_lat], [to_lng, to_lat]]},
                headers={"Authorization": api_key},
                timeout=ORS_TIMEOUT,
            )
            resp.raise_for_status()
            feature = resp.json()["features"][0]
            summary = feature["properties"]["summary"]
            route = {
                "geometry": feature["geometry"],
                "distance_m": round(summary["distance"], 1),
                "duration_s": round(summary["duration"], 1),
                "is_estimate": False,
            }
        except (requests.RequestException, KeyError, IndexError, ValueError):
            route = None

    if route is None:
        return _estimate(from_lat, from_lng, to_lat, to_lng)

    _cache[key] = route
    return route
