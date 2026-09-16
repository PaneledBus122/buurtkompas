"""Score-to-color mapping for the choropleth map.

Kept separate from both the DB layer (data.py) and the Streamlit UI
(app.py) so the color scale itself is a pure, independently testable
function — no Streamlit, no pydeck, no DB connection required to verify it.

Drop this module in ``src/buurtkompas/dashboard/colors.py``.
"""

from __future__ import annotations

from itertools import pairwise

# Five-stop diverging scale: blue (worst) -> gray (median) -> orange (best).
# Not red/green: that pairing is indistinguishable to the ~8% of men with
# red-green color vision deficiency, the single most common form of color
# blindness — blue/orange is one of the standard colorblind-safe diverging
# pairs (e.g. ColorBrewer's RdYlBu-style alternatives) and still reads
# clearly as "which side of average" at a glance, the same design goal the
# old red/yellow/green scale had.
_COLOR_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (0.0, (0x24, 0x50, 0x8F)),  # blue
    (0.25, (0x9F, 0xB4, 0xD2)),  # light blue
    (0.5, (0xC7, 0xC4, 0xB8)),  # neutral gray
    (0.75, (0xE3, 0xB2, 0x7B)),  # light orange
    (1.0, (0xC8, 0x6A, 0x1D)),  # orange
]

# Neutral gray for buurten that didn't clear the coverage threshold
# (category_score IS NULL in fct_category_score) — deliberately desaturated
# so "no data" reads as visually distinct from "bad score" (blue), not
# confusable with it. Kept close to (but not identical to) the scale's own
# neutral/median stop above, which is a real score (0.5), not "no data".
NO_DATA_COLOR: list[int] = [200, 200, 200, 120]

FILL_ALPHA = 200


def score_to_color(score: float | None) -> list[int]:
    """Map a category_score in [0, 1] (or None) to an RGBA fill color.

    ``score`` of None means the region didn't clear fct_category_score's
    coverage-threshold gate (see the dbt mart) — rendered as
    ``NO_DATA_COLOR`` rather than silently defaulting to blue or orange,
    which would misrepresent "we don't know" as "this is bad/good".

    For a real score, linearly interpolates between the two ``_COLOR_STOPS``
    the value falls between. E.g. score=0.875 falls in the [0.75, 1.0]
    segment, halfway from light orange to orange.
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


def score_to_hex(score: float | None) -> str:
    """Same mapping as score_to_color, as a "#rrggbb" string (no alpha) —
    for CSS contexts (the ranked-buurten table's color dots) that don't
    understand pydeck's [r, g, b, a] list format.
    """
    r, g, b, _alpha = score_to_color(score)
    return f"#{r:02x}{g:02x}{b:02x}"


def legend_gradient_css() -> str:
    """A CSS ``linear-gradient`` built from the same ``_COLOR_STOPS`` the
    map itself uses, so the legend rendered in app.py can never drift out
    of sync with the actual choropleth colors — one source of truth for
    both.
    """
    stops = ", ".join(
        f"#{r:02x}{g:02x}{b:02x} {pos:.0%}" for pos, (r, g, b) in _COLOR_STOPS
    )
    return f"linear-gradient(to right, {stops})"
