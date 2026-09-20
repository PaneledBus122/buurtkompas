"""Streamlit dashboard (Phase 5): a choropleth map of buurt category
scores, with no AI/natural-language layer yet (that's Phase 7).

All data access and geometry/color transforms live in data.py/colors.py —
this module is UI wiring only (widgets, layout, handing data to pydeck).
Most of the visual theme (accent color, fonts, dark palette, radii,
sidebar colors) lives in .streamlit/config.toml, Streamlit's own native
theming — the CSS injected here (inject_custom_css) only covers the
handful of things that config can't express: the score-color-driven
ranked-table dots/bars, the map's gradient legend, and a few custom
section labels/cards.

Usage:
    uv run streamlit run src/buurtkompas/dashboard/app.py

Requires: `uv add streamlit pydeck` (on top of the existing sqlalchemy/
psycopg2 dependencies from the Load step).

Drop this module in ``src/buurtkompas/dashboard/app.py``.
"""

from __future__ import annotations

import html
import math

import pydeck as pdk
import requests
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from buurtkompas.dashboard import commute, static_pages
from buurtkompas.dashboard.colors import legend_gradient_css
from buurtkompas.dashboard.data import (
    DATABASE_URL,
    build_feature_collection,
    compute_overall_score,
    compute_view_state,
    fetch_available_categories,
    fetch_category_scores,
    fetch_region_geometries,
    fetch_region_points,
    fetch_region_scores,
    merge_region_scores,
    scale_bar_widths,
)
from buurtkompas.dashboard.footer import render_footer

# Not a real dim_indicator category (it's never written to the DB — see
# commute.py's module docstring), but treated as one in the sidebar
# selector once a lookup has been computed, per the feature's "selectable
# layer alongside the existing categories" requirement.
COMMUTE_CATEGORY = "commute"

# Also not a real dim_indicator category — a user-adjustable weighted
# composite of all 6 stored categories (see data.compute_overall_score),
# always available (unlike COMMUTE_CATEGORY, which only appears after a
# successful address lookup) and the default selection, since "which
# buurt is best overall" is this dashboard's core question.
OVERALL_CATEGORY = "overall"

# Category slug -> human-readable label for the selector. Falls back to the
# raw slug (via .get(category, category)) for any category added to
# dim_indicator that hasn't been given a label here yet, so a new category
# shows up immediately instead of erroring. Key order also drives the
# "Overall" view's slider order below.
CATEGORY_LABELS: dict[str, str] = {
    "schools": "Education",
    "amenities": "Amenities",
    "quiet_nature": "Quiet & Nature",
    "housing": "Housing",
    "income": "Income",
    "safety": "Safety",
}

DEFAULT_SLIDER_VALUE = 5
SLIDER_MIN = 0
SLIDER_MAX = 10

# Must match .streamlit/config.toml's [theme] primaryColor — config.toml
# drives Streamlit's own theming (buttons, sliders, focus rings), but the
# custom CSS below (things config.toml can't express, like the commute
# card's tint) needs the same value in Python to build rgba()s from it.
ACCENT_COLOR = "#2EC4B6"


def inject_custom_css() -> None:
    """Custom CSS for the handful of things Streamlit's native theming
    (.streamlit/config.toml) can't express: layout/typography for a few
    custom-built elements (the brand block, section labels, the commute
    card, the map's legend, the ranked-buurten table's per-row dot/bar).
    Colors, fonts, and every standard widget's accent are themed via
    config.toml instead of here, so they can't drift out of sync with it.

    Uses st.markdown (not st.html): a style-only st.html() body gets
    routed to Streamlit's "event container" (added for its own issue
    #9388, to avoid a style block taking up layout space) — which in
    practice never actually lands the <style> tag in the page's DOM.
    st.markdown's unsafe_allow_html path has no such special-casing and
    reliably renders inline <style> blocks, which is the point here.
    """
    st.markdown(
        f"""
        <style>
        .bk-brand {{
            display: flex;
            align-items: center;
            gap: 0.6rem;
            padding-bottom: 1rem;
            margin-bottom: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }}
        .bk-brand-icon {{ font-size: 1.5rem; line-height: 1; }}
        .bk-brand-name {{
            font-family: var(--font-heading, inherit);
            font-size: 1.15rem;
            font-weight: 700;
            color: {ACCENT_COLOR};
            line-height: 1.15;
        }}
        .bk-brand-tagline {{
            font-size: 0.65rem;
            font-weight: 500;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: rgba(255, 255, 255, 0.5);
        }}

        .bk-section-label {{
            font-size: 0.7rem;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: rgba(255, 255, 255, 0.55);
            margin: 0.25rem 0 0.5rem 0;
        }}
        .bk-section-label--accent {{ color: {ACCENT_COLOR}; }}

        /* Streamlit assigns containers created with container(key=...) the
        CSS class "st-key-<key>" -- this tints/borders the commute-time
        card so it visually reads as its own overlay feature, separate
        from the category-weights composite score below it. */
        .st-key-commute_section {{
            background-color: rgba(46, 196, 182, 0.07);
            border: 1px solid rgba(46, 196, 182, 0.3);
            border-radius: 0.75rem;
            padding: 0.9rem 1rem 1.1rem 1rem;
            margin-bottom: 1.25rem;
        }}

        .bk-legend {{ margin-top: 0.6rem; }}
        .bk-legend-bar {{
            height: 10px;
            border-radius: 5px;
            background: {legend_gradient_css()};
        }}
        .bk-legend-labels {{
            display: flex;
            justify-content: space-between;
            font-size: 0.7rem;
            color: rgba(255, 255, 255, 0.55);
            margin-top: 0.3rem;
        }}

        .bk-rank-header {{
            display: flex;
            align-items: baseline;
            justify-content: space-between;
        }}
        .bk-rank-range {{
            font-size: 0.7rem;
            color: rgba(255, 255, 255, 0.4);
        }}
        .bk-rank-table {{ max-height: 32rem; overflow-y: auto; }}
        .bk-rank-row {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.4rem 0.2rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            font-size: 0.85rem;
        }}
        .bk-rank-num {{
            width: 1.4rem;
            flex-shrink: 0;
            text-align: right;
            color: rgba(255, 255, 255, 0.4);
        }}
        .bk-rank-dot {{
            width: 0.55rem;
            height: 0.55rem;
            border-radius: 50%;
            flex-shrink: 0;
        }}
        .bk-rank-name {{
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .bk-rank-bar-track {{
            width: 4rem;
            height: 6px;
            flex-shrink: 0;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 3px;
            overflow: hidden;
        }}
        .bk-rank-bar-fill {{ display: block; height: 100%; border-radius: 3px; }}
        .bk-rank-score {{
            width: 2.6rem;
            flex-shrink: 0;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_brand() -> None:
    st.sidebar.html("""
        <div class="bk-brand">
            <span class="bk-brand-icon">🧭</span>
            <div>
                <div class="bk-brand-name">buurtkompas</div>
                <div class="bk-brand-tagline">Eindhoven &amp; Veldhoven &middot; Buurtvergelijker</div>
            </div>
        </div>
    """)


def render_header(methodology_page: st.Page) -> None:
    """The dashboard's title and a short methodology teaser.

    The teaser is deliberately short: the full explanation (categories,
    the Overall score's weighting/renormalization, commute time) lives on
    its own page (static_pages.render_methodology_page), reachable from
    here and from the footer on every page.
    """
    st.title("Eindhoven & Veldhoven neighborhood comparison")
    with st.expander("Scoring methodology"):
        st.write(
            "Category scores are percentile ranks within the region's own "
            "gemeente (1.0 = best, 0.0 = worst). Gray / N/A means the buurt "
            "didn't clear the minimum data-coverage threshold for this "
            "category."
        )
        st.page_link(methodology_page, label="Full methodology")


@st.cache_resource
def get_engine() -> Engine:
    """One pooled connection per Streamlit server process, not per session —
    cache_resource (not cache_data) is what Streamlit intends for
    non-serializable, share-safe objects like a SQLAlchemy Engine.

    This engine (and its pooled connections) lives for as long as the
    Cloud Run container stays warm, which is far longer than Neon's ~5
    minute auto-suspend window after a quiet period — without the options
    below, a pooled connection left idle across a suspend goes stale
    server-side, and the next checkout fails with
    "SSL connection has been closed unexpectedly" before the real query
    even runs. `pool_pre_ping` catches that by validating a connection on
    checkout and transparently replacing it if it's dead; `pool_recycle`
    (set below Neon's suspend window) recycles connections proactively so
    most of the time pre_ping doesn't even need to catch anything.
    """
    return create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=280)


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


def render_weight_sliders(available_categories: list[str]) -> dict[str, float]:
    """Render one 0-10 slider per category (default 5 = equal weight) with
    its live normalized percentage inline in the label (e.g. "Education
    17%"), plus a reset action, and return weights summing to 1 — the
    shape compute_overall_score expects.

    Deliberately not cached: the whole point is that every drag
    recomputes and re-renders the map/table from live widget state (see
    main()), and the underlying query is only ~116 rows either way.
    """
    st.sidebar.html('<p class="bk-section-label">Category weights</p>')
    slider_categories = [c for c in CATEGORY_LABELS if c in available_categories]

    # A reset click sets this flag and reruns (see the button below) rather
    # than mutating st.session_state[f"weight_{category}"] directly at that
    # point: Streamlit raises StreamlitWidgetAlreadyInstantiatedError if you
    # mutate a widget's own session_state key after that widget has already
    # been instantiated in the same run (which the sliders below always
    # have been, since the button is rendered after them). Consuming the
    # flag here, before any slider widget exists this run, avoids that.
    if st.session_state.pop("reset_weights_pending", False):
        for category in slider_categories:
            st.session_state[f"weight_{category}"] = DEFAULT_SLIDER_VALUE

    pending_persona_weights = st.session_state.pop("pending_persona_weights", None)
    if pending_persona_weights is not None:
        for category, value in pending_persona_weights.items():
            if category in slider_categories:
                st.session_state[f"weight_{category}"] = value

    # Read each slider's last-known value *before* instantiating the
    # widgets below, so the percentage baked into each slider's own label
    # reflects the values about to be rendered this run -- Streamlit
    # updates session_state for a just-changed widget before the script
    # reruns, so this is never one interaction behind.
    prior_values = {
        category: st.session_state.get(f"weight_{category}", DEFAULT_SLIDER_VALUE)
        for category in slider_categories
    }
    prior_total = sum(prior_values.values())
    prior_percentages = (
        {c: v / prior_total for c, v in prior_values.items()}
        if prior_total > 0
        else dict.fromkeys(slider_categories, 1 / len(slider_categories))
    )

    raw_weights: dict[str, int] = {
        category: st.sidebar.slider(
            f"{CATEGORY_LABELS.get(category, category)} {prior_percentages[category]:.0%}",
            min_value=SLIDER_MIN,
            max_value=SLIDER_MAX,
            value=DEFAULT_SLIDER_VALUE,
            key=f"weight_{category}",
        )
        for category in slider_categories
    }

    if st.sidebar.button("Reset to equal weights", type="tertiary"):
        st.session_state["reset_weights_pending"] = True
        # The sliders above already rendered with this run's (pre-reset)
        # values; force an immediate rerun so the reset is reflected now
        # instead of looking like it takes an extra click.
        st.rerun()

    total = sum(raw_weights.values())
    if total == 0:
        # Every slider dragged to 0 at once: fall back to equal weights
        # rather than dividing by zero and feeding compute_overall_score a
        # composite that's NaN for every region.
        return dict.fromkeys(slider_categories, 1 / len(slider_categories))
    return {category: value / total for category, value in raw_weights.items()}


def load_overall_feature_collection(engine: Engine, weights: dict[str, float]) -> dict:
    category_scores = fetch_category_scores(engine)
    overall = compute_overall_score(category_scores, weights)
    # compute_overall_score returns NaN (pandas/numpy's "no value") for a
    # region that didn't clear the coverage threshold; merge_region_scores
    # / build_feature_collection expect the same None convention every
    # other category uses, so translate at this boundary.
    overall_scores = {
        region_id: (None if math.isnan(score) else float(score))
        for region_id, score in overall.items()
    }
    geometries = fetch_region_geometries(engine)
    rows = merge_region_scores(geometries, overall_scores)
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
    st.pydeck_chart(deck, width="stretch")
    render_legend()


def render_legend() -> None:
    """The map's blue-gray-orange gradient, with tick labels, so a viewer
    doesn't have to guess which end of the color scale is "better" — the
    same _COLOR_STOPS the map itself uses (colors.legend_gradient_css),
    so this can never visually disagree with the choropleth.
    """
    st.html("""
        <div class="bk-legend">
            <div class="bk-legend-bar"></div>
            <div class="bk-legend-labels">
                <span>0.0 worse</span>
                <span>0.5 avg</span>
                <span>1.0 better</span>
            </div>
        </div>
    """)


def render_score_table(feature_collection: dict) -> None:
    rows = [f["properties"] for f in feature_collection["features"]]
    rows_sorted = sorted(
        rows,
        # NULL scores sort last regardless of ascending/descending, same
        # spirit as the dbt mart's own NULL handling: "no data" is neither
        # the best nor the worst score, so it shouldn't rank as either.
        key=lambda p: (p["category_score"] is None, -(p["category_score"] or 0)),
    )
    rows_with_bars = scale_bar_widths(rows_sorted)

    real_scores = [
        r["category_score"] for r in rows_sorted if r["category_score"] is not None
    ]
    range_label = (
        f"bar: {min(real_scores):.2f}-{max(real_scores):.2f}" if real_scores else ""
    )

    st.html(f"""
        <div class="bk-rank-header">
            <span class="bk-section-label" style="margin:0;">Ranked buurten</span>
            <span class="bk-rank-range">{range_label}</span>
        </div>
    """)

    row_html = []
    for rank, row in enumerate(rows_with_bars, start=1):
        bar_pct = row["bar_pct"]
        bar_style = (
            f"width:{bar_pct:.0f}%;background:{row['color_hex']};"
            if bar_pct is not None
            else "width:0%;"
        )
        row_html.append(
            '<div class="bk-rank-row">'
            f'<span class="bk-rank-num">{rank}</span>'
            f'<span class="bk-rank-dot" style="background:{row["color_hex"]}"></span>'
            f'<span class="bk-rank-name">{html.escape(row["name"])}</span>'
            '<span class="bk-rank-bar-track">'
            f'<span class="bk-rank-bar-fill" style="{bar_style}"></span>'
            "</span>"
            f'<span class="bk-rank-score">{row["score_label"]}</span>'
            "</div>"
        )
    st.html(f'<div class="bk-rank-table">{"".join(row_html)}</div>')


def render_dashboard_page(methodology_page: st.Page) -> None:
    """Home page: the interactive dashboard. Behavior/layout unchanged by
    the site-structure work — the sidebar (commute card, category
    selector, category weights, reset) is exactly what it was before;
    only a footer is now appended after this renders (see main()).
    """
    inject_custom_css()
    render_sidebar_brand()
    render_header(methodology_page)

    categories = load_categories()
    if not categories:
        st.error(
            "No categories found in dim_indicator — has the Load step "
            "(`uv run python -m buurtkompas.load.loader`) been run yet?"
        )
        return

    with st.sidebar.container(key="commute_section"):
        st.html(
            '<p class="bk-section-label bk-section-label--accent">📍 Commute time · overlay</p>'
        )
        address = st.text_input(
            "Destination address", placeholder="e.g. Eindhoven Centraal Station"
        )
        # A button, not a call on every keystroke: text_input reruns the
        # script on each character typed, and this lookup burns real ORS
        # API quota.
        if st.button("Compute commute time", type="primary") and address.strip():
            try:
                st.session_state["commute_scores"] = load_commute_scores(
                    address.strip()
                )
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
            st.error(st.session_state["commute_error"])

    options = [OVERALL_CATEGORY, *categories]
    if "commute_scores" in st.session_state:
        options = [*options, COMMUTE_CATEGORY]

    category = st.sidebar.selectbox(
        "Category",
        options=options,
        format_func=lambda c: (
            "Overall"
            if c == OVERALL_CATEGORY
            else f"Commute time to {st.session_state.get('commute_address', '')}"
            if c == COMMUTE_CATEGORY
            else CATEGORY_LABELS.get(c, c)
        ),
    )

    if category == OVERALL_CATEGORY:
        weights = render_weight_sliders(categories)
        feature_collection = load_overall_feature_collection(get_engine(), weights)
    elif category == COMMUTE_CATEGORY:
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
        render_score_table(feature_collection)


def main() -> None:
    """Entry point: registers Home (the dashboard) plus the four static
    informational pages (Methodology, About, Privacy, Contact) as an
    explicit list of st.Page objects -- not the automatic pages/
    directory convention -- and turns off Streamlit's own automatic
    sidebar page list (position="hidden") so the sidebar stays exactly
    the dashboard's own. The informational pages are reachable only
    through footer.render_footer's links, appended after every page's
    own content below.
    """
    st.set_page_config(page_title="buurtkompas", layout="wide")

    def with_footer(page_fn):
        def wrapped() -> None:
            page_fn()
            # `pages` is defined below, after this closure -- fine here,
            # since `wrapped` isn't actually called until st.navigation
            # dispatches to it, by which point `pages` is fully built.
            render_footer(pages)

        return wrapped

    # A plain wrapper (not render_dashboard_page itself) so it satisfies
    # st.Page's zero-argument Callable[[], None] while still threading
    # through the Methodology page it links to from its own teaser.
    def home_page() -> None:
        render_dashboard_page(methodology_page)

    methodology_page = st.Page(
        with_footer(static_pages.render_methodology_page),
        title="Methodology",
        url_path="methodology",
    )

    pages = [
        st.Page(with_footer(home_page), title="Home", url_path="home", default=True),
        methodology_page,
        st.Page(
            with_footer(static_pages.render_about_page),
            title="About",
            url_path="about",
        ),
        st.Page(
            with_footer(static_pages.render_privacy_page),
            title="Privacy",
            url_path="privacy",
        ),
        st.Page(
            with_footer(static_pages.render_contact_page),
            title="Contact",
            url_path="contact",
        ),
    ]

    nav = st.navigation(pages, position="hidden")
    nav.run()


if __name__ == "__main__":
    main()
