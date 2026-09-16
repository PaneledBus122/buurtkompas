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
        "Where you end up living quietly shapes a lot of your life — how "
        "long your commute is, whether your kids can walk to school, how "
        "well you sleep at night, who you run into at the corner shop. "
        "Yet most people choose a neighbourhood on a handful of viewings "
        "and a feeling, because that's all that's easy to get."
    )
    st.markdown(
        "That feels backwards. The information to make a fairer choice "
        "already exists — it's public, it's free, it's just scattered "
        "across statistics offices and government portals in a form "
        "nobody but a specialist would enjoy reading. Buurtkompas exists "
        "to close that gap: to take what public data can tell you about a "
        "neighbourhood in and around Eindhoven and put it in front of "
        "anyone deciding where to live, in one place, on equal footing."
    )
    st.markdown(
        "That matters most for the people with the least local knowledge "
        "to fall back on — someone moving to Eindhoven from another "
        "country, another city, or into their first place of their own, "
        "who's never had the years it takes to build the kind of "
        '"everyone knows that street" instinct a longtime resident has '
        "for free. Public data doesn't care how long you've lived "
        "somewhere. Read fairly, it can hand a newcomer roughly the same "
        "starting point as a local."
    )
    st.markdown(
        "That's the hope behind this project: not to tell anyone where to "
        "live, but to make sure the choice starts from the same solid "
        "ground for everyone who has to make it. How the numbers behind "
        "it are actually calculated is laid out in full on the "
        "Methodology page, so none of it has to be taken on faith."
    )
    st.markdown("Questions, or something that looks off? See the Contact page.")


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
