"""Overall stock capacity for a food bank.

A food bank tracks three stock categories separately - perishables, non
perishables and toiletries - each as a "how full are we" percentage. The overall
figure the map shows is a weighted average of the three.

Weights are equal thirds for now, but kept explicit so the average is genuinely
weighted and the mix can be tuned later without touching the maths.

Pure functions only - no database, no Flask, standard library only.
"""

WEIGHTS = {
    "perishables": 1 / 3,
    "non_perishables": 1 / 3,
    "toiletries": 1 / 3,
}


def overall_capacity(perishables, non_perishables, toiletries):
    """Weighted average of the category percentages, in [0.0, 100.0].

    Categories that have never been reported (``None``) are left out and the
    weights are renormalised across whatever remains. Returns ``None`` when no
    category has been reported at all.
    """
    values = {
        "perishables": perishables,
        "non_perishables": non_perishables,
        "toiletries": toiletries,
    }
    present = {k: v for k, v in values.items() if v is not None}
    if not present:
        return None
    total_weight = sum(WEIGHTS[k] for k in present)
    weighted = sum(WEIGHTS[k] * v for k, v in present.items())
    return round(weighted / total_weight, 1)
