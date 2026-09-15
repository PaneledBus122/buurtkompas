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

from sqlalchemy import text
from sqlalchemy.engine import Engine

from buurtkompas.dashboard.colors import score_to_color

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://buurtkompas:buurtkompas_dev@localhost:5432/buurtkompas",
)

# Must match dbt_project.yml's `vars.data_year` until the dashboard grows a
# year selector — both this and the dbt models currently assume Kerncijfers
# wijken en buurten's single-year (2024) snapshot.
DATA_YEAR = 2024


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
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


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
