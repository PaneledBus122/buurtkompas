"""Data-access and geometry-transform layer for the Streamlit dashboard.

Deliberately separated from app.py (the Streamlit/pydeck UI layer) per the
project's UI/data separation principle: everything here is plain
Python/SQLAlchemy with no Streamlit or pydeck import, so it can be
unit-tested (see tests/test_dashboard_data.py) without spinning up a
Streamlit process.

Drop this module in ``src/buurtkompas/dashboard/data.py``.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from buurtkompas.dashboard.colors import score_to_color, score_to_hex

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://buurtkompas:buurtkompas_dev@localhost:5432/buurtkompas",
)

# Must match dbt_project.yml's `vars.data_year` until the dashboard grows a
# year selector — both this and the dbt models currently assume Kerncijfers
# wijken en buurten's single-year (2024) snapshot.
DATA_YEAR = 2024

# A region needs at least this many of the 6 stored categories with a
# non-null category_score to get an overall_score at all — ceil(6 / 2),
# the same majority-coverage bar fct_category_score itself uses per
# category (see dbt/models/marts/fct_category_score.sql), just applied one
# level up, across categories instead of across indicators.
MIN_CATEGORIES_FOR_OVERALL = 3


def fetch_available_categories(engine: Engine) -> list[str]:
    """Distinct category slugs, for populating the category selector.

    Reads dim_indicator (the Load-step raw table), not fct_category_score,
    so a category still appears in the dropdown even in a hypothetical
    dataset where no single region has cleared its coverage threshold yet.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text("select distinct category from dim_indicator order by category")
        )
        return [row[0] for row in rows]


def fetch_region_scores(engine: Engine, category: str) -> list[dict[str, Any]]:
    """One row per buurt for the given category: name, score, geometry.

    LEFT JOIN (rather than INNER) so a buurt with no row at all in
    fct_category_score for this category — e.g. it never cleared the
    coverage-threshold gate — still comes back with category_score=None
    instead of silently vanishing from the map.
    """
    query = text("""
        select
            r.region_id,
            r.name,
            s.category_score,
            ST_AsGeoJSON(r.geometry) as geometry_json
        from dim_region r
        left join analytics.fct_category_score s
            on r.region_id = s.region_id
            and s.category = :category
            and s.year = :year
        order by r.region_id
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"category": category, "year": DATA_YEAR})
        return [
            {
                "region_id": row.region_id,
                "name": row.name,
                "category_score": row.category_score,
                "geometry": json.loads(row.geometry_json),
            }
            for row in rows
        ]


def fetch_category_scores(engine: Engine) -> pd.DataFrame:
    """Long-format (region_id, gemeente_code, category, category_score) —
    one row per (region, category) pair across all 6 stored categories,
    the raw input compute_overall_score needs to build a weighted
    composite per buurt.

    Reads fct_category_score directly rather than going through
    fetch_region_scores (which fetches one category and its geometry at a
    time): the "Overall" view needs every category for every region in one
    shot, and doesn't need geometry from this query at all — the map is
    built separately from fetch_region_geometries + merge_region_scores,
    same as the commute-time layer.
    """
    query = text("""
        select region_id, gemeente_code, category, category_score
        from analytics.fct_category_score
        where year = :year
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"year": DATA_YEAR})


def compute_overall_score(
    category_scores: pd.DataFrame, weights: dict[str, float]
) -> pd.Series:
    """Weighted composite of category_score across categories, re-ranked as
    a percentile within each region's gemeente — same convention as any
    single category_score (1.0 = best, NaN = doesn't clear the coverage
    threshold).

    `category_scores` is fetch_category_scores' long-format
    (region_id, gemeente_code, category, category_score) table — it never
    contains a "commute" row (commute-time is a live, address-triggered
    overlay computed in commute.py, not a stored fct_category_score
    category), so this is excluded from the composite by construction, not
    by filtering. `weights` maps each of the 6 stored categories to a
    weight; the caller is expected to have already normalized these to sum
    to 1 (app.py's sliders do this) — but this function renormalizes again
    per region over just that region's *available* (non-null) categories,
    so a missing category doesn't silently deflate the composite by
    dropping its weight instead of redistributing it to the rest.

    A region needs at least MIN_CATEGORIES_FOR_OVERALL non-null category
    scores; below that its entry is NaN rather than a composite computed
    from a thin, unrepresentative subset.

    Returns a Series of overall_score indexed by region_id, covering every
    region_id present in `category_scores` (including ones that end up
    NaN), so a caller can always look up any region without a KeyError.
    """
    all_regions = category_scores["region_id"].unique()
    gemeente_by_region = (
        category_scores.drop_duplicates("region_id")
        .set_index("region_id")["gemeente_code"]
        .reindex(all_regions)
    )

    usable = category_scores.dropna(subset=["category_score"]).copy()
    usable["weight"] = usable["category"].map(weights).astype(float)

    # Renormalize over just the categories this region actually has, so
    # e.g. a region missing `income` gets its weight redistributed
    # proportionally across the other 5, rather than the composite simply
    # losing income's share of the total.
    weight_totals = usable.groupby("region_id")["weight"].transform("sum")
    usable["weighted_score"] = (usable["weight"] / weight_totals) * usable[
        "category_score"
    ]

    available_category_counts = usable.groupby("region_id")["category"].transform(
        "nunique"
    )
    usable = usable[available_category_counts >= MIN_CATEGORIES_FOR_OVERALL]

    # min_count=1: an all-NaN group (e.g. every available category's weight
    # happened to be 0, so weight_totals was 0 and weighted_score is NaN
    # throughout) must sum to NaN, not silently to 0.0 -- pandas' default
    # skipna=True sum of an all-NaN group is 0.0, which would misreport as
    # "worst possible score" instead of "no usable weights".
    overall_raw = usable.groupby("region_id")["weighted_score"].sum(min_count=1)
    overall_raw = overall_raw.reindex(all_regions)  # NaN for excluded regions

    # rank(pct=True) on a groupby leaves NaN entries as NaN (na_option
    # defaults to "keep") and computes the percentile among only the
    # non-null values within each gemeente_code group — exactly the
    # "partitioned by city, N/A doesn't participate in ranking" behavior
    # fct_category_score's own percent_rank() gives at the category level.
    return (
        overall_raw.groupby(gemeente_by_region).rank(pct=True).rename("overall_score")
    )


def fetch_region_points(engine: Engine) -> list[dict[str, Any]]:
    """One row per buurt: id plus its representative (lon, lat) point —
    load/loader.py's ST_PointOnSurface-backfilled columns. Used as the
    Matrix API's origins by the live commute-time feature
    (dashboard/commute.py), which needs plain coordinates, not geometry.
    """
    query = text("select region_id, lon, lat from dim_region order by region_id")
    with engine.connect() as conn:
        rows = conn.execute(query)
        return [
            {"region_id": row.region_id, "lon": row.lon, "lat": row.lat} for row in rows
        ]


def fetch_region_geometries(engine: Engine) -> list[dict[str, Any]]:
    """One row per buurt: id, name, geometry — the same shape
    fetch_region_scores returns, minus category_score. Used to build a map
    feature collection for the commute-time layer, whose scores come from a
    live computation (commute.compute_commute_percentiles) rather than from
    fct_category_score.
    """
    query = text("""
        select region_id, name, ST_AsGeoJSON(geometry) as geometry_json
        from dim_region
        order by region_id
    """)
    with engine.connect() as conn:
        rows = conn.execute(query)
        return [
            {
                "region_id": row.region_id,
                "name": row.name,
                "geometry": json.loads(row.geometry_json),
            }
            for row in rows
        ]


def merge_region_scores(
    geometries: list[dict[str, Any]], scores: dict[str, float | None]
) -> list[dict[str, Any]]:
    """Pure transform: attach a region_id -> score mapping (e.g. live
    commute percentiles) onto fetch_region_geometries' rows, producing the
    same {region_id, name, category_score, geometry} shape
    fetch_region_scores returns from the DB — so build_feature_collection
    can render either without knowing which one it got. A region missing
    from `scores` (shouldn't happen; every region is queried) still gets an
    explicit None rather than a KeyError, same "no data" shape as a region
    that never cleared fct_category_score's coverage threshold.
    """
    return [
        {**geometry, "category_score": scores.get(geometry["region_id"])}
        for geometry in geometries
    ]


def build_feature_collection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure transform: DB rows -> a GeoJSON FeatureCollection for pydeck's
    GeoJsonLayer, with a display-ready fill_color and score_label baked into
    each feature's properties.

    Kept separate from fetch_region_scores precisely so this — and the color
    mapping it drives — is unit-testable with plain dict fixtures, no DB.
    """
    features = []
    for row in rows:
        score = row["category_score"]
        features.append(
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "region_id": row["region_id"],
                    "name": row["name"],
                    "category_score": score,
                    "score_label": "N/A" if score is None else f"{score:.2f}",
                    "fill_color": score_to_color(score),
                    "color_hex": score_to_hex(score),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def scale_bar_widths(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure transform: attach a `bar_pct` (0-100) to each row, min-max
    scaled against only the non-null `category_score` values actually
    present in `rows` — not the full [0, 1] range. This is deliberately
    *not* the same scale the map/legend use (those span the full 0-1
    percentile range on purpose): the ranked-buurten table only ever shows
    a handful of rows at a time, and if e.g. every visible row scores
    0.90-1.00, scaling bars to [0, 1] would render them all as nearly-full
    bars with no visible distinction between them. Scaling to the shown
    rows' own min-max keeps that distinction visible. The printed numeric
    score, not this bar, stays the source of truth for the actual value.

    A row with `category_score` of None gets `bar_pct` of None (an
    empty/hidden bar, not a misleading 0%-width bar that would look like
    "measured, and worst").
    """
    scores = [
        row["category_score"] for row in rows if row["category_score"] is not None
    ]

    if not scores:
        return [{**row, "bar_pct": None} for row in rows]

    lo, hi = min(scores), max(scores)
    span = hi - lo

    def _bar_pct(score: float | None) -> float | None:
        if score is None:
            return None
        if span == 0:
            # Every shown row ties -- a full bar for all of them reads
            # better than a 0-width bar for all of them.
            return 100.0
        return (score - lo) / span * 100

    return [{**row, "bar_pct": _bar_pct(row["category_score"])} for row in rows]


def compute_view_state(feature_collection: dict[str, Any]) -> dict[str, float]:
    """Pure transform: derive the map's initial lat/lon/zoom from the data's
    own bounding box, rather than hardcoding Eindhoven's coordinates — so
    this keeps working unmodified once a second gemeente is loaded (the
    schema's `gemeente_code`-partitioned design already anticipates this;
    see eindhoven-dashboard-plan.md).

    The zoom figure is a coarse heuristic (bigger bounding box -> zoom out
    further), not a precise viewport-fit computation — adequate for an MVP
    where the region set is always exactly one gemeente at a time, revisit
    if/when the dashboard needs to fit multiple gemeenten in one view.
    """
    lons: list[float] = []
    lats: list[float] = []

    def _walk(coords: Any) -> None:
        # GeoJSON coordinate arrays nest to different depths depending on
        # geometry type (Polygon vs. MultiPolygon buurt boundaries); recursing
        # until hitting a [lon, lat] pair handles both without a type switch.
        if (
            isinstance(coords, list)
            and len(coords) == 2
            and all(isinstance(c, int | float) for c in coords)
        ):
            lons.append(coords[0])
            lats.append(coords[1])
        elif isinstance(coords, list):
            for c in coords:
                _walk(c)

    for feature in feature_collection["features"]:
        _walk(feature["geometry"]["coordinates"])

    if not lons or not lats:
        # No geometry at all (empty region set) — de-zoomed view of the
        # Netherlands as a safe fallback rather than crashing pydeck with a
        # NaN center.
        return {"latitude": 52.1, "longitude": 5.3, "zoom": 6.0}

    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    span = max(max_lon - min_lon, max_lat - min_lat)

    # Rough log2 relationship between a bounding-box span (in degrees) and a
    # web-mercator zoom level that fits it on screen. The constants (12.0
    # baseline, 0.1-degree reference span) are tuned by eye against a
    # single-city span (~0.05-0.2 degrees) — not derived from the Mercator
    # projection formula — so re-tune if the dashboard starts rendering
    # spans far outside that range (e.g. a whole province).
    zoom = 12.0 - math.log2(max(span, 1e-4) / 0.1)
    zoom = max(3.0, min(15.0, zoom))

    return {
        "latitude": (min_lat + max_lat) / 2,
        "longitude": (min_lon + max_lon) / 2,
        "zoom": zoom,
    }
