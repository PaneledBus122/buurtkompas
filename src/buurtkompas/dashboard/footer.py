"""Reusable footer shown at the bottom of every page (the dashboard and
the four static informational pages) — the *only* way to reach the
informational pages, since they're deliberately excluded from the
sidebar (see app.py's navigation setup, st.navigation(..., position=
"hidden")).

Kept generic (renders whatever `pages` list it's given) and free of any
import of the page modules themselves, so this stays a leaf module —
app.py's navigation setup is the one place that both builds the page
list and wires each page's content function to it, avoiding a circular
import between "the page that renders a footer" and "the list of pages
the footer links to".

Drop this module in ``src/buurtkompas/dashboard/footer.py``.
"""

from __future__ import annotations

import streamlit as st


def render_footer(pages: list[st.Page]) -> None:
    """A single, visually subdued row of links to every page (including
    the current one) — small font, muted gray, a top border to separate
    it from the page's own content, e.g. "Home · Methodology · About ·
    Privacy · Contact".

    Uses st.page_link (not raw <a> tags): it's what makes these actual
    Streamlit page-switch links rather than full page reloads, and it's
    the only way to link to a page that's outside the (hidden) sidebar.

    Note on st.html vs st.markdown: a *style-only* st.html() body is
    routed by this Streamlit version to an internal "event container"
    that never actually lands the <style> tag in the page's DOM (see
    app.py's inject_custom_css for the fuller writeup) — so the CSS below
    uses st.markdown(unsafe_allow_html=True) instead, which has no such
    special-casing.
    """
    with st.container(key="site_footer"):
        st.markdown(
            """
            <style>
            .st-key-site_footer {
                margin-top: 2rem;
                padding-top: 0.75rem;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
            }
            .st-key-site_footer [data-testid="stPageLink-NavLink"] {
                font-size: 0.8rem;
                color: rgba(255, 255, 255, 0.55) !important;
            }
            .st-key-site_footer [data-testid="stPageLink-NavLink"] span {
                color: rgba(255, 255, 255, 0.55) !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        # A trailing empty spacer column keeps the links packed to the
        # left, reading as a compact footer nav rather than 5 links
        # spread across the full page width.
        # label is omitted deliberately: st.Page's own `title` isn't
        # readable back from the object here (it's populated once the
        # page is registered with st.navigation, not at construction
        # time) -- st.page_link already falls back to the page's own
        # title internally when label is None.
        *link_cols, _spacer = st.columns([1] * len(pages) + [4])
        for col, page in zip(link_cols, pages):
            with col:
                st.page_link(page)
