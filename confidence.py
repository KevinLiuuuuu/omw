"""Confidence decay for resource status reports.

A report is fully trusted (1.0) the moment it is made and its confidence decays
exponentially with age. How fast it decays depends on the resource type: shelter
beds change by the hour, pantry stock over an afternoon, free wifi barely at all.

Pure functions only - no database, no Flask, standard library only.
"""

HOUR = 3600
DAY = 24 * HOUR

# Half-life in seconds per resource kind: the age at which confidence drops to 0.5.
HALF_LIFE_SECONDS = {
    "pantry": 2 * HOUR,
    "shelter": 1 * HOUR,
    "wifi": 7 * DAY,
}

# Fallback for unknown kinds: assume it goes stale as fast as shelter beds.
DEFAULT_HALF_LIFE_SECONDS = 1 * HOUR


def half_life_seconds(kind):
    """Half-life for a resource kind, falling back to the default for unknowns."""
    return HALF_LIFE_SECONDS.get(kind, DEFAULT_HALF_LIFE_SECONDS)


def decay(age_seconds, half_life):
    """Exponential decay factor in [0.0, 1.0].

    Zero (or negative, e.g. clock skew) age gives 1.0; each `half_life` seconds
    halves the value.
    """
    if age_seconds <= 0:
        return 1.0
    return 0.5 ** (age_seconds / half_life)


def confidence(kind, age_seconds):
    """Confidence in a `kind` report that is `age_seconds` old, in [0.0, 1.0]."""
    return decay(age_seconds, half_life_seconds(kind))


def blend(old_value, old_confidence, new_value):
    """Fold a fresh report into the existing estimate.

    The old estimate is weighted by its own confidence (0.0-1.0, from `confidence`
    above) and the new report at full weight:

        blended = (old_value * old_confidence + new_value) / (old_confidence + 1)

    So a stale old value (confidence near 0) is almost entirely overwritten by the
    new report, while a fresh one (confidence near 1) only shifts halfway toward
    it. With no prior estimate (`old_value` is None) the new report stands alone.
    """
    if old_value is None:
        return float(new_value)
    return (old_value * old_confidence + new_value) / (old_confidence + 1.0)
