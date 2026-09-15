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
import requests
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from buurtkompas.dashboard import commute
from buurtkompas.dashboard.data import (
    DATABASE_URL,
    build_feature_collection,
    compute_view_state,
    fetch_available_categories,
    fetch_region_geometries,
    fetch_region_points,
    fetch_region_scores,
    merge_region_scores,
)

# Not a real dim_indicator category (it's never written to the DB — see
# commute.py's module docstring), but treated as one in the sidebar
# selector once a lookup has been computed, per the feature's "selectable
# layer alongside the existing categories" requirement.
COMMUTE_CATEGORY = "commute"

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


@st.cache_data(show_spinner="Looking up commute times…")
def load_commute_scores(address: str) -> dict[str, float | None]:
    """Geocode `address` and compute a commute-time percentile per buurt.

    Cached on the address string alone: Streamlit reruns this whole script
    on every widget interaction, and this call burns real ORS API quota
    (one geocode + one matrix request), so a re-run with the same address
    must be free. Raises ValueError for an address ORS can't geocode, and
    lets RuntimeError (missing ORS_API_KEY) / requests.RequestException
    (ORS unreachable, timed out, 4xx/5xx) propagate — main() below turns
    each into a user-facing st.error instead of letting it crash the app.
    """
    origins = fetch_region_points(get_engine())
    destination = commute.geocode_address(address)
    if destination is None:
        raise ValueError(
            f'Could not find a location for "{address}". Try a more '
            "specific address (street, house number, city)."
        )

    origin_coords = [(row["lon"], row["lat"]) for row in origins]
    minutes = commute.fetch_commute_minutes(destination, origin_coords)
    durations_by_region = {
        row["region_id"]: minute for row, minute in zip(origins, minutes)
    }
    return commute.compute_commute_percentiles(durations_by_region)


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
    st.pydeck_chart(deck, width="stretch")


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
        width="stretch",
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

    st.sidebar.divider()
    st.sidebar.subheader("Commute time")
    address = st.sidebar.text_input(
        "Destination address", placeholder="e.g. Eindhoven Centraal Station"
    )
    # A button, not a call on every keystroke: text_input reruns the script
    # on each character typed, and this lookup burns real ORS API quota.
    if st.sidebar.button("Compute commute time") and address.strip():
        try:
            st.session_state["commute_scores"] = load_commute_scores(address.strip())
            st.session_state["commute_address"] = address.strip()
            st.session_state.pop("commute_error", None)
        except RuntimeError as exc:  # ORS_API_KEY not set
            st.session_state.pop("commute_scores", None)
            st.session_state["commute_error"] = str(exc)
        except ValueError as exc:  # address not recognized by ORS
            st.session_state.pop("commute_scores", None)
            st.session_state["commute_error"] = str(exc)
        except requests.RequestException:  # ORS unreachable, timed out, 4xx/5xx
            st.session_state.pop("commute_scores", None)
            st.session_state["commute_error"] = (
                "Couldn't reach the routing service (ORS). Please try again "
                "in a moment."
            )

    if st.session_state.get("commute_error"):
        st.sidebar.error(st.session_state["commute_error"])

    options = list(categories)
    if "commute_scores" in st.session_state:
        options = [*options, COMMUTE_CATEGORY]

    category = st.sidebar.selectbox(
        "Category",
        options=options,
        format_func=lambda c: (
            f"Commute time to {st.session_state.get('commute_address', '')}"
            if c == COMMUTE_CATEGORY
            else CATEGORY_LABELS.get(c, c)
        ),
    )

    if category == COMMUTE_CATEGORY:
        geometries = fetch_region_geometries(get_engine())
        rows = merge_region_scores(geometries, st.session_state["commute_scores"])
        feature_collection = build_feature_collection(rows)
    else:
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
