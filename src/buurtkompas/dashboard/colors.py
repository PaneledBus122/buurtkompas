"""Score-to-color mapping for the choropleth map.

Kept separate from both the DB layer (data.py) and the Streamlit UI
(app.py) so the color scale itself is a pure, independently testable
function — no Streamlit, no pydeck, no DB connection required to verify it.

Drop this module in ``src/buurtkompas/dashboard/colors.py``.
"""

from __future__ import annotations

from itertools import pairwise

# Three-stop diverging scale: red (worst) -> yellow (median) -> green (best).
# Chosen over a single-hue sequential scale because category_score is a
# percentile (0=worst, 1=best) where the qualitative "good vs. bad" framing
# matters more than showing fine-grained magnitude — a viewer should be able
# to tell "below vs. above average" at a glance without reading the legend.
_COLOR_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (0.0, (215, 48, 39)),  # red
    (0.5, (255, 255, 191)),  # yellow
    (1.0, (26, 152, 80)),  # green
]

# Neutral gray for buurten that didn't clear the coverage threshold
# (category_score IS NULL in fct_category_score) — deliberately desaturated
# so "no data" reads as visually distinct from "bad score" (red), not
# confusable with it.
NO_DATA_COLOR: list[int] = [200, 200, 200, 120]

FILL_ALPHA = 200


def score_to_color(score: float | None) -> list[int]:
    """Map a category_score in [0, 1] (or None) to an RGBA fill color.

    ``score`` of None means the region didn't clear fct_category_score's
    coverage-threshold gate (see the dbt mart) — rendered as
    ``NO_DATA_COLOR`` rather than silently defaulting to red or green,
    which would misrepresent "we don't know" as "this is bad/good".

    For a real score, linearly interpolates between the two ``_COLOR_STOPS``
    the value falls between. E.g. score=0.75 falls in the [0.5, 1.0] segment,
    25% of the way from yellow to green.
    """
    if score is None:
        return NO_DATA_COLOR

    clamped = max(0.0, min(1.0, score))

    for (lo_pos, lo_rgb), (hi_pos, hi_rgb) in pairwise(_COLOR_STOPS):
        if lo_pos <= clamped <= hi_pos:
            # Fraction of the way from the lower stop to the upper stop.
            t = 0.0 if hi_pos == lo_pos else (clamped - lo_pos) / (hi_pos - lo_pos)
            rgb = [round(lo + (hi - lo) * t) for lo, hi in zip(lo_rgb, hi_rgb)]
            return [*rgb, FILL_ALPHA]

    # Unreachable given the clamp above and stops spanning [0, 1], but keeps
    # the function total rather than letting a float rounding edge case
    # raise instead of degrading gracefully.
    return NO_DATA_COLOR
