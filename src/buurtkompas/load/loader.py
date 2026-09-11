"""Load extracted CBS indicator values and PDOK geometries into Postgres/PostGIS.

Reads:
    data/raw/cbs_eindhoven.csv          (long format, already category-tagged
                                          by extract/cbs.py — columns:
                                          region_id, indicator_id,
                                          indicator_label, category, value)
    data/raw/pdok_eindhoven_buurten.geojson

Writes:
    dim_region, dim_indicator, fact_indicator  (see load/schema.py)

Category tagging is NOT done here — cbs.py already assigns `category` per
indicator during extraction. This module only fills in `unit`, which isn't
tracked upstream, via a small local lookup table below.

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
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from buurtkompas.load.schema import dim_indicator, dim_region, fact_indicator, metadata

RAW_DIR = Path("data/raw")
CBS_CSV = RAW_DIR / "cbs_eindhoven.csv"
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
}


def _reset_tables(engine: Engine) -> None:
    """Full refresh: drop existing rows in dependency order (facts first)."""
    with engine.begin() as conn:
        conn.execute(fact_indicator.delete())
        conn.execute(dim_indicator.delete())
        conn.execute(dim_region.delete())


def load_dim_region(engine: Engine) -> None:
    gdf = gpd.read_file(PDOK_GEOJSON)
    gdf = gdf.rename(columns={"buurtcode": "region_id", "buurtnaam": "name"})
    gdf["region_level"] = "buurt"
    gdf = gdf[["region_id", "region_level", "name", "geometry"]]
    gdf.to_postgis("dim_region", engine, if_exists="append", index=False)


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
    cbs_df = pd.read_csv(CBS_CSV)

    _reset_tables(engine)
    load_dim_region(engine)
    load_dim_indicator(engine, cbs_df)
    load_fact_indicator(engine, cbs_df)
    print("Load complete: dim_region, dim_indicator, fact_indicator populated.")


if __name__ == "__main__":
    main()
