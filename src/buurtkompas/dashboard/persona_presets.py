"""Prototype: evidence-informed starting weights for buurtkompas's six
scoring categories, selectable via persona preset buttons, ahead of a
later natural-language front-end. See the project's weighting-methodology
design notes for the sourcing behind these numbers (Leefbaarometer,
NAR generational/buyer surveys) -- TEMPORARY validation UI, not final."""

from __future__ import annotations

import streamlit as st

CATEGORIES = ["schools", "amenities", "quiet_nature", "housing", "income", "safety"]

# Baseline for the reference combination: 30s / no children / low
# relocation urgency / moderate budget. Pattern (amenities & safety
# highest, quiet_nature lowest) follows the Leefbaarometer dimension
# weighting (voorzieningen & overlast/onveiligheid highest, fysieke
# omgeving lowest).
BASE_WEIGHTS = {
    "schools": 15,
    "amenities": 22,
    "quiet_nature": 13,
    "housing": 15,
    "income": 15,
    "safety": 20,
}

# Each axis uses reference-level coding: one level has an all-zero delta
# row (the level baked into BASE_WEIGHTS above), other levels are defined
# relative to it. Rows are designed to sum to 0 (pure reallocation, not a
# change in total).
AGE_DELTA = {
    "20s": {
        "schools": -2,
        "amenities": 3,
        "quiet_nature": -3,
        "housing": -1,
        "income": 2,
        "safety": 1,
    },
    "30s": dict.fromkeys(CATEGORIES, 0),
    "40s": {
        "schools": 1,
        "amenities": -1,
        "quiet_nature": 1,
        "housing": 0,
        "income": 0,
        "safety": -1,
    },
    "50s": {
        "schools": -1,
        "amenities": -2,
        "quiet_nature": 2,
        "housing": 1,
        "income": 1,
        "safety": -1,
    },
    "60s": {
        "schools": -3,
        "amenities": -3,
        "quiet_nature": 4,
        "housing": 1,
        "income": 1,
        "safety": 0,
    },
    "70+": {
        "schools": -3,
        "amenities": -4,
        "quiet_nature": 4,
        "housing": 0,
        "income": 1,
        "safety": 2,
    },
}

CHILDREN_DELTA = {
    "no": dict.fromkeys(CATEGORIES, 0),
    "yes": {
        "schools": 6,
        "amenities": 1,
        "quiet_nature": 1,
        "housing": 1,
        "income": -10,
        "safety": 1,
    },
}

# "Job/relocation urgency" has no direct scoring category of its own
# (commute time is a separate live map layer via OpenRouteService, not
# part of this weighted score) -- reflected indirectly via amenities /
# quiet_nature / safety. Revisit if commute time ever becomes a scored
# category.
JOB_URGENCY_DELTA = {
    "low": dict.fromkeys(CATEGORIES, 0),
    "medium": {
        "schools": -1,
        "amenities": 2,
        "quiet_nature": -2,
        "housing": 0,
        "income": 0,
        "safety": 1,
    },
    "high": {
        "schools": -2,
        "amenities": 4,
        "quiet_nature": -4,
        "housing": -2,
        "income": 1,
        "safety": 3,
    },
}

BUDGET_DELTA = {
    "tight": {
        "schools": -3,
        "amenities": -3,
        "quiet_nature": -4,
        "housing": 8,
        "income": 5,
        "safety": -3,
    },
    "moderate": dict.fromkeys(CATEGORIES, 0),
    "flexible": {
        "schools": 2,
        "amenities": 3,
        "quiet_nature": 4,
        "housing": -6,
        "income": -5,
        "safety": 2,
    },
}

FLOOR_PERCENT = 3  # no category's share ever collapses below this


def compute_weights(
    age: str, children: str, job_urgency: str, budget: str
) -> dict[str, float]:
    """Additive ("linear opinion pool") combination of the four axes over
    BASE_WEIGHTS, floor-clipped and renormalized to sum to 100. Assumes
    the axes act independently (no interaction terms) -- a documented
    simplification, not an empirically validated one."""
    raw = dict(BASE_WEIGHTS)
    for delta_table, level in (
        (AGE_DELTA, age),
        (CHILDREN_DELTA, children),
        (JOB_URGENCY_DELTA, job_urgency),
        (BUDGET_DELTA, budget),
    ):
        for category in CATEGORIES:
            raw[category] += delta_table[level][category]
    clipped = {c: max(raw[c], FLOOR_PERCENT) for c in CATEGORIES}
    total = sum(clipped.values())
    return {c: clipped[c] / total * 100 for c in CATEGORIES}


# (label, tooltip, age, children, job_urgency, budget)
PERSONAS: list[tuple[str, str, str, str, str, str]] = [
    (
        "New job, moving fast",
        "20s, no kids, just landed a new job and relocating quickly, tight budget",
        "20s",
        "no",
        "high",
        "tight",
    ),
    (
        "Young family",
        "30s, two kids, stable job, moderate budget",
        "30s",
        "yes",
        "low",
        "moderate",
    ),
    (
        "Enjoying single life",
        "40s, single, stable, comfortable budget",
        "40s",
        "no",
        "low",
        "flexible",
    ),
    (
        "Settled with teens",
        "50s, teenage kids, stable job, comfortable budget",
        "50s",
        "yes",
        "low",
        "flexible",
    ),
    (
        "Easing into retirement",
        "60s, kids grown and moved out, comfortable budget",
        "60s",
        "no",
        "low",
        "flexible",
    ),
    (
        "Retired, tight budget",
        "70s+, living on a pension, tight budget",
        "70+",
        "no",
        "low",
        "tight",
    ),
    (
        "Twenties, no rush",
        "20s, no kids, no urgency to move, comfortable budget",
        "20s",
        "no",
        "low",
        "flexible",
    ),
    (
        "Career change, tight budget",
        "30s, single, urgent career change, tight budget",
        "30s",
        "no",
        "high",
        "tight",
    ),
    (
        "Young kids, tight budget",
        "40s, young children, considering a job change, tight budget",
        "40s",
        "yes",
        "medium",
        "tight",
    ),
    (
        "Re-entering job market",
        "50s, kids grown, urgent career change, moderate budget",
        "50s",
        "no",
        "high",
        "moderate",
    ),
]


def _weights_to_slider_values(weights: dict[str, float]) -> dict[str, int]:
    """Convert a 0-100 share back to the sliders' 0-10 integer scale.
    Only relative proportions matter -- render_weight_sliders renormalizes
    whatever ints it reads -- but the 0.3 factor keeps the total in the
    same ballpark as today's default-equal-weights state (6 x 5 = 30)."""
    return {c: max(0, min(10, round(share * 0.3))) for c, share in weights.items()}


def render_persona_presets() -> None:
    """Temporary validation UI: a bank of persona buttons that jump the
    category-weight sliders to precomputed values. Not intended to ship
    long-term as-is -- kept isolated in this module so it's easy to
    remove once the weighting model and, later, its natural-language
    front-end are validated."""
    st.write("**Try a persona** (temporary preview of evidence-based starting weights)")
    rows = [PERSONAS[0:5], PERSONAS[5:10]]
    for row in rows:
        cols = st.columns(len(row))
        for col, (label, tooltip, age, children, urgency, budget) in zip(
            cols, row, strict=True
        ):
            with col:
                if st.button(label, help=tooltip, key=f"persona_{label}"):
                    weights = compute_weights(age, children, urgency, budget)
                    # Safe only because this renders before the sidebar sliders exist in this run.
                    for category, value in _weights_to_slider_values(weights).items():
                        st.session_state[f"weight_{category}"] = value
