"""The four informational pages (Methodology, About, Privacy, Contact) —
placeholder copy for now, per the site-structure work order; only the
layout is meant to be final here, not the wording.

Reachable only via footer.render_footer's links (see app.py's navigation
setup), never from the sidebar — these are plain content pages, so they
carry no widgets, no DB access, and no Streamlit caching of their own.

Drop this module in ``src/buurtkompas/dashboard/static_pages.py``.
"""

from __future__ import annotations

import streamlit as st


def render_methodology_page() -> None:
    st.title("How scores are calculated")
    st.markdown(
        "Every score on this dashboard is computed the same way, from open "
        "data published by Statistics Netherlands (CBS) and PDOK — no "
        "manual judgment calls about individual neighbourhoods."
    )
    st.markdown(
        "**Category scores.** Buurtkompas groups public indicators into "
        "six categories: Education, Amenities, Quiet & Nature, Housing, "
        "Income, and Safety. Within each category, every neighbourhood "
        "(buurt) is ranked against every other buurt in the same "
        "municipality (gemeente) on each underlying indicator, and those "
        "ranks are combined into a single 0–1 percentile score for that "
        "category. A score of 1.0 means the neighbourhood is at or near "
        "the top of its municipality on that category; 0.0 means the "
        "opposite. A neighbourhood needs at least half of a category's "
        "underlying indicators to have data before that category gets a "
        "score at all — otherwise it is shown as not available (N/A) "
        "rather than guessed at."
    )
    st.markdown(
        "**Overall score.** The Overall score lets you weigh the six "
        "categories yourself with the sliders in the sidebar. It is a "
        "weighted average of whichever category scores are actually "
        "available for a neighbourhood, with your weights renormalized "
        "over just those available categories (so a missing category is "
        "left out of the average rather than counted as zero). A "
        "neighbourhood needs at least three of the six categories present "
        "to get an Overall score. That weighted average is then re-ranked "
        "as a percentile across all neighbourhoods in the same "
        "municipality, the same way the category scores are — so the "
        "Overall score stays on the same 0–1 scale and keeps the same "
        "meaning ('better than X% of this municipality') no matter how "
        "you set the weights."
    )
    st.markdown(
        "**Commute time.** The commute-time overlay is calculated "
        "separately by looking up the address you enter and computing "
        "travel time to every neighbourhood. It is not part of the "
        "Overall score or any category — it's a separate lens you can "
        "add on top."
    )
    st.markdown(
        "Data sources: CBS (Statistics Netherlands) neighbourhood key "
        "figures, and PDOK (Publieke Dienstverlening Op de Kaart) for "
        "geographic boundaries and routing. *[Placeholder — refine with "
        "the exact indicator list per category, data vintage/year, and "
        "update cadence.]*"
    )
    st.markdown(
        "This project and its full source code are open on GitHub: "
        "[repo link placeholder]."
    )


def render_about_page() -> None:
    st.title("About this project")
    st.markdown(
        "Buurtkompas compares neighbourhoods (buurten) in Eindhoven, the "
        "Netherlands, side by side using public open data, so you can look "
        "at more than one neighbourhood's reputation or gut feeling when "
        "deciding where to live."
    )
    st.markdown(
        "This is a personal data-engineering portfolio project built by "
        "Seongjoon Lim, a condensed-matter physics researcher moving into "
        "software/data engineering. It's meant to demonstrate an "
        "end-to-end data pipeline and a small production web app, not to "
        "be a commercial product: batch ETL from CBS and PDOK open data, "
        "transformation and scoring with dbt (staging → intermediate → "
        "marts), a Postgres/PostGIS database (hosted on Neon), an "
        "interactive Streamlit + pydeck dashboard, and deployment on "
        "Google Cloud Run with GitHub Actions CI/CD."
    )
    st.markdown(
        "The scoring methodology is explained in full on the Methodology "
        "page. The complete source code, including the dbt models and the "
        "dashboard itself, is open on GitHub: [repo link placeholder]."
    )
    st.markdown("Questions, bug reports, or ideas are welcome — see the Contact page.")


def render_privacy_page() -> None:
    st.title("Privacy")
    st.markdown(
        "Buurtkompas does not collect or store any personal data, and it "
        "does not use cookies, analytics, or tracking of any kind."
    )
    st.markdown(
        "The only personal input this app accepts is the destination "
        "address you optionally type in for the commute-time feature. "
        "That address is sent to a routing service (OpenRouteService) "
        "only to compute travel times for the current session, and it is "
        "not logged, stored, or shared anywhere by this app."
    )
    st.markdown(
        "All neighbourhood data shown here is public, aggregate, open "
        "data from CBS and PDOK — it describes places, not individual "
        "people."
    )
    st.markdown("Questions about this? See the Contact page.")


def render_contact_page() -> None:
    st.title("Contact & feedback")
    st.markdown(
        "This is a personal portfolio project, maintained by one person, "
        "so there's no support team or ticketing system — just a couple "
        "of direct ways to reach me:"
    )
    st.markdown(
        "- Found a bug, have a feature idea, or spotted something wrong "
        "in the data? Open an issue on GitHub: [repo issues link "
        "placeholder].\n"
        "- Anything else? [email placeholder]."
    )
    st.markdown("Response times are best-effort, since this is a side project.")
