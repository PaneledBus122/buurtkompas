"""SQLAlchemy Core schema for the buurtkompas warehouse (Phase 2: Load).

Long/EAV-style schema per the project plan (`eindhoven-dashboard-plan.md`):

    dim_region      (region_id, region_level, name, gemeente_code, geometry)
    dim_indicator   (indicator_id, category, unit, source, description)
    fact_indicator  (region_id, indicator_id, year, value, percentile_score)

This is kept as plain SQLAlchemy Core (not the ORM) because Phase 3 (dbt)
owns the actual analytical marts — this layer is just a landing zone that
mirrors the raw extracted data, so there's no need for ORM-level relationship
mapping here.

Requires: `uv add sqlalchemy geoalchemy2 psycopg2-binary`

Drop this module in ``src/buurtkompas/load/schema.py``.
"""

from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

metadata = MetaData()

dim_region = Table(
    "dim_region",
    metadata,
    Column("region_id", String, primary_key=True),  # buurtcode, e.g. "BU07721234"
    Column("region_level", String, nullable=False),  # "buurt" | "wijk" | "gemeente"
    Column("name", String, nullable=False),
    # Needed to PARTITION BY in Phase 3 dbt ranking (rank within a city, not
    # across the whole country) — see eindhoven-dashboard-plan.md, "Phase 3/7
    # 스코어링 방법론". Not unique/PK on its own; many regions share one gemeente.
    Column("gemeente_code", String, nullable=False),  # e.g. "GM0772"
    # MULTIPOLYGON (not POLYGON): CBS buurt boundaries can be non-contiguous
    # (e.g. split by a river or highway), so a plain Polygon type would
    # reject some valid buurt geometries.
    Column(
        "geometry", Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False
    ),
)

dim_indicator = Table(
    "dim_indicator",
    metadata,
    Column("indicator_id", String, primary_key=True),  # slug, e.g. "school_distance_km"
    Column("category", String, nullable=False),
    Column("unit", String, nullable=False),
    Column("source", String, nullable=False),  # e.g. "CBS StatLine 85984NED"
    Column("description", String, nullable=True),
)

fact_indicator = Table(
    "fact_indicator",
    metadata,
    Column("region_id", String, ForeignKey("dim_region.region_id"), primary_key=True),
    Column(
        "indicator_id",
        String,
        ForeignKey("dim_indicator.indicator_id"),
        primary_key=True,
    ),
    Column("year", Integer, primary_key=True),
    Column("value", Float, nullable=True),
    # Populated later by dbt (Phase 3), not by this Load step.
    Column("percentile_score", Float, nullable=True),
    UniqueConstraint(
        "region_id", "indicator_id", "year", name="uq_fact_indicator_natural_key"
    ),
)
