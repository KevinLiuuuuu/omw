"""Is a resource open right now, from its published opening hours.

Hours are stored per weekday as a list of ``[open, close]`` "HH:MM" pairs, so a
day can have a midday break (two intervals) or be closed (empty list). A missing
day key is treated as closed.

    {"mon": [["09:00", "15:00"]], "tue": [], ...}

Pure functions only - no database, no Flask, no timezone handling (the caller
passes a datetime already in the resource's local time), standard library only.
"""

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse(hhmm):
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def is_open(hours, now):
    """Whether ``now`` falls inside an opening interval.

    ``hours`` is the parsed per-weekday dict, or ``None`` when a resource has no
    published hours - in which case this returns ``None`` (unknown) rather than a
    guess. ``now`` is a datetime already in the resource's local time. Intervals
    are half-open: open at the start minute, closed at the end minute.
    """
    if hours is None:
        return None
    intervals = hours.get(DAY_KEYS[now.weekday()], [])
    minutes = now.hour * 60 + now.minute
    return any(
        _parse(start) <= minutes < _parse(end) for start, end in intervals
    )
