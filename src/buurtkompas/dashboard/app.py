"""Streamlit baseline dashboard (Phase 5): a choropleth map of buurt
category scores, with no AI/natural-language layer yet (that's Phase 7).

All data access and geometry/color transforms live in data.py/colors.py —
this module is UI wiring only (widgets, layout, handing data to pydeck).

Usage:
    uv run streamlit run src/buurtkompas/dashboard/app.py

Requires: `uv add streamlit pydeck` (on top of the existing sqlalchemy/
psycopg2 dependencies from the Load step).

Drop this module in ``src/buurtkompas/dashboard/app.py``.
"""

from __future__ import annotations

import pydeck as pdk
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from buurtkompas.dashboard.data import (
    DATABASE_URL,
    build_feature_collection,
    compute_view_state,
    fetch_available_categories,
    fetch_region_scores,
)

# Category slug -> human-readable label for the selector. Falls back to the
# raw slug (via .get(category, category)) for any category added to
# dim_indicator that hasn't been given a label here yet, so a new category
# (e.g. the planned `safety`) shows up immediately instead of erroring.
CATEGORY_LABELS: dict[str, str] = {
    "education": "Education",
    "amenities": "Amenities",
    "quiet_nature": "Quiet & Nature",
    "housing": "Housing",
    "income": "Income",
    "safety": "Safety",
}


@st.cache_resource
def get_engine() -> Engine:
    """One pooled connection per Streamlit server process, not per session —
    cache_resource (not cache_data) is what Streamlit intends for
    non-serializable, share-safe objects like a SQLAlchemy Engine.
    """
    return create_engine(DATABASE_URL)


@st.cache_data(ttl=300)
def load_categories() -> list[str]:
    return fetch_available_categories(get_engine())


@st.cache_data(ttl=300)
def load_feature_collection(category: str) -> dict:
    rows = fetch_region_scores(get_engine(), category)
    return build_feature_collection(rows)


def render_map(feature_collection: dict) -> None:
    layer = pdk.Layer(
        "GeoJsonLayer",
        feature_collection,
        get_fill_color="properties.fill_color",
        get_line_color=[90, 90, 90],
        line_width_min_pixels=1,
        stroked=True,
        filled=True,
        pickable=True,
        auto_highlight=True,
    )
    view_state = pdk.ViewState(**compute_view_state(feature_collection))
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        # CARTO's free Positron style (OSM-based, no API key/Mapbox token
        # required) — see eindhoven-dashboard-plan.md's basemap decision.
        # A MapLibre+PMTiles custom basemap is the planned stretch upgrade.
        map_style=pdk.map_styles.CARTO_LIGHT,
        tooltip={"text": "{name}\n{score_label}"},
    )
    st.pydeck_chart(deck, use_container_width=True)


def render_score_table(feature_collection: dict) -> None:
    rows = [f["properties"] for f in feature_collection["features"]]
    rows_sorted = sorted(
        rows,
        # NULL scores sort last regardless of ascending/descending, same
        # spirit as the dbt mart's own NULL handling: "no data" is neither
        # the best nor the worst score, so it shouldn't rank as either.
        key=lambda p: (p["category_score"] is None, -(p["category_score"] or 0)),
    )
    st.dataframe(
        [{"Buurt": r["name"], "Score": r["score_label"]} for r in rows_sorted],
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    st.set_page_config(page_title="buurtkompas", layout="wide")
    st.title("buurtkompas — Eindhoven neighborhood comparison")
    st.caption(
        "Category scores are percentile ranks within the region's own "
        "gemeente (1.0 = best, 0.0 = worst). Gray / N/A means the buurt "
        "didn't clear the minimum data-coverage threshold for this "
        "category — see the project README for the scoring methodology."
    )

    categories = load_categories()
    if not categories:
        st.error(
            "No categories found in dim_indicator — has the Load step "
            "(`uv run python -m buurtkompas.load.loader`) been run yet?"
        )
        return

    category = st.sidebar.selectbox(
        "Category",
        options=categories,
        format_func=lambda c: CATEGORY_LABELS.get(c, c),
    )

    feature_collection = load_feature_collection(category)
    if not feature_collection["features"]:
        st.warning("No regions returned for this category.")
        return

    col_map, col_table = st.columns([3, 1])
    with col_map:
        render_map(feature_collection)
    with col_table:
        st.subheader("Ranked buurten")
        render_score_table(feature_collection)


if __name__ == "__main__":
    main()
