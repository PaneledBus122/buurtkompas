"""Load extracted CBS/politie indicator values and PDOK geometries into
Postgres/PostGIS.

Reads:
    data/raw/cbs_eindhoven.csv          (long format, already category-tagged
                                          by extract/cbs.py — columns:
                                          region_id, indicator_id,
                                          indicator_label, category, value)
    data/raw/politie_eindhoven.csv      (same long-format columns, from
                                          extract/politie.py)
    data/raw/cbs_population_eindhoven.csv  (region_id, population —
                                          normalization denominator, from
                                          extract/cbs.py's extract_population())
    data/raw/pdok_eindhoven_buurten.geojson

Writes:
    dim_region, dim_indicator, fact_indicator  (see load/schema.py)

Category tagging is NOT done here — cbs.py/politie.py already assign
`category` per indicator during extraction. This module only fills in
`unit`, which isn't tracked upstream, via a small local lookup table below.

Refresh strategy: full truncate-and-reload of all three tables on every run.
Simpler and safer than upserting for a small nightly batch (fine for Phase 4's
Airflow DAG later) — revisit if the tables grow large enough that a full
reload becomes slow.

Usage:
    uv run python -m buurtkompas.load.loader

Requires: `uv add sqlalchemy geoalchemy2 psycopg2-binary`

Drop this module in ``src/buurtkompas/load/loader.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from buurtkompas.load.schema import dim_indicator, dim_region, fact_indicator, metadata

RAW_DIR = Path("data/raw")
CBS_CSV = RAW_DIR / "cbs_eindhoven.csv"
CBS_POPULATION_CSV = RAW_DIR / "cbs_population_eindhoven.csv"
POLITIE_CSV = RAW_DIR / "politie_eindhoven.csv"
PDOK_GEOJSON = RAW_DIR / "pdok_eindhoven_buurten.geojson"

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://buurtkompas:buurtkompas_dev@localhost:5432/buurtkompas",
)

# Kerncijfers wijken en buurten 2024 is a single-year snapshot; there's no
# `year` column in the extracted CSV, so it's fixed here. Revisit if/when
# the extractor starts pulling multiple years.
YEAR = 2024

# cbs.py tags `category` but not `unit` — filled in here by indicator_id.
# Extend this whenever a new CBS indicator is added to the extractor.
UNIT_BY_INDICATOR_ID: dict[str, str] = {
    "D000045": "km",  # Afstand tot school
    "D000025": "km",  # Afstand tot grote supermarkt
    "D000029": "km",  # Afstand tot kinderdagverblijf
    "D000028": "km",  # Afstand tot huisartsenpraktijk
    "ST0001": "ordinal (1-5)",  # Mate van stedelijkheid
    "M001642": "EUR",  # Gemiddelde WOZ-waarde van woningen
    "1014800": "%",  # Koopwoningen (%)
    "1014850_2": "%",  # Huurwoningen totaal (%)
    "M000224": "EUR",  # Gemiddeld inkomen per inwoner
    "0.0.0": "aantal",  # Geregistreerde misdrijven (totaal aantal) — politie.py
}


def _reset_tables(engine: Engine) -> None:
    """Full refresh: drop existing rows in dependency order (facts first)."""
    with engine.begin() as conn:
        conn.execute(fact_indicator.delete())
        conn.execute(dim_indicator.delete())
        conn.execute(dim_region.delete())


def load_dim_region(engine: Engine) -> None:
    gdf = gpd.read_file(PDOK_GEOJSON)
    gdf = gdf.rename(
        columns={
            "buurtcode": "region_id",
            "buurtnaam": "name",
            "gemeentecode": "gemeente_code",
        }
    )
    gdf["region_level"] = "buurt"

    # Population comes from CBS (cbs.extract_population()), not PDOK, so
    # it's merged in rather than renamed from an existing geojson column.
    population_df = pd.read_csv(CBS_POPULATION_CSV)
    gdf = gdf.merge(population_df, on="region_id", how="left")

    gdf = gdf[
        ["region_id", "region_level", "name", "gemeente_code", "population", "geometry"]
    ]
    gdf.to_postgis("dim_region", engine, if_exists="append", index=False)
    _backfill_region_points(engine)


def _backfill_region_points(engine: Engine) -> None:
    """Fill dim_region.lon/lat from each buurt's geometry, one time, right
    after the geometry load.

    ST_PointOnSurface (not ST_Centroid): a centroid is the mean of all
    boundary points and can land outside a concave or multi-part buurt
    polygon; ST_PointOnSurface is guaranteed to fall inside it. This matters
    because these points become Matrix API origins for the dashboard's live
    commute-time feature (dashboard/commute.py) — an origin outside the
    buurt would silently measure commute time from the wrong neighborhood.

    Done as a Postgres-side UPDATE (not computed client-side with
    GeoPandas/Shapely) specifically so it uses PostGIS's own
    ST_PointOnSurface implementation, per the feature spec.
    """
    with engine.begin() as conn:
        conn.execute(
            text("""
                update dim_region
                set
                    lon = ST_X(ST_PointOnSurface(geometry)),
                    lat = ST_Y(ST_PointOnSurface(geometry))
            """)
        )


def load_dim_indicator(engine: Engine, cbs_df: pd.DataFrame) -> None:
    indicators = cbs_df[
        ["indicator_id", "indicator_label", "category"]
    ].drop_duplicates()

    unassigned = indicators.loc[
        indicators["category"].isin(["unassigned", "", None]), "indicator_id"
    ].tolist()
    if unassigned:
        raise ValueError(
            f"Indicator(s) {unassigned} have no category assigned "
            "(category='unassigned'). Fix the category mapping in "
            "extract/cbs.py and re-run the extractor before loading — "
            "categorizing here in the loader would hide the gap at its "
            "actual source."
        )

    missing_units = set(indicators["indicator_id"]) - set(UNIT_BY_INDICATOR_ID)
    if missing_units:
        raise ValueError(
            f"No unit defined for indicator_id(s) {missing_units}. "
            "Add them to UNIT_BY_INDICATOR_ID in loader.py."
        )

    rows = [
        {
            "indicator_id": row.indicator_id,
            "category": row.category,
            "unit": UNIT_BY_INDICATOR_ID[row.indicator_id],
            "source": "CBS StatLine 85984NED",
            "description": row.indicator_label,
        }
        for row in indicators.itertuples()
    ]
    pd.DataFrame(rows).to_sql("dim_indicator", engine, if_exists="append", index=False)


def load_fact_indicator(engine: Engine, cbs_df: pd.DataFrame) -> None:
    df = cbs_df[["region_id", "indicator_id", "value"]].copy()
    df["year"] = YEAR
    df.to_sql("fact_indicator", engine, if_exists="append", index=False)


def main() -> None:
    engine = create_engine(DATABASE_URL)
    metadata.create_all(engine)  # idempotent: no-op for tables that already exist

    # cbs.py and politie.py both emit the same long-format columns
    # (region_id, indicator_id, indicator_label, category, value), so their
    # extracts are simply concatenated into one indicator/fact table.
    indicator_df = pd.concat(
        [pd.read_csv(CBS_CSV), pd.read_csv(POLITIE_CSV)], ignore_index=True
    )

    _reset_tables(engine)
    load_dim_region(engine)
    load_dim_indicator(engine, indicator_df)
    load_fact_indicator(engine, indicator_df)
    print("Load complete: dim_region, dim_indicator, fact_indicator populated.")


if __name__ == "__main__":
    main()
