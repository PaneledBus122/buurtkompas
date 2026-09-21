"""Structured profile form: collects five facts about the user's situation
and applies the resulting starting category weights to the sidebar sliders
in one step. Replaces the old persona-preset buttons (removed in this
change) as the dashboard's way of getting evidence-informed starting
weights, ahead of a later natural-language front-end (see the project's
weighting-methodology design notes).

The slider bounds and scale factor below (0-10, 0.3) intentionally
duplicate app.py's SLIDER_MIN / SLIDER_MAX / DEFAULT_SLIDER_VALUE rather
than importing them: app.py imports this module, so importing back would be
circular, and the values are small and stable. If the slider scale ever
changes, update both places.
"""

from __future__ import annotations

import streamlit as st

from buurtkompas.weighting.engine import (
    AgeGroup,
    BudgetSensitivity,
    EnvironmentPreference,
    RelocationUrgency,
    UserProfile,
    compute_weights,
)

_SLIDER_MIN = 0
_SLIDER_MAX = 10

# Widgets start at the engine's own baseline, so an untouched form describes
# exactly UserProfile().
_BASELINE = UserProfile()


def weights_to_slider_values(weights: dict[str, float]) -> dict[str, int]:
    """Convert a 0-100 share (summing to 100) to the sidebar sliders' 0-10
    integer scale. Only relative proportions matter -- render_weight_sliders
    renormalizes whatever ints it reads -- but the 0.3 factor keeps the
    total in the same ballpark as the sliders' default-equal-weights state
    (6 categories x default value 5 = 30).
    """
    return {
        category: max(_SLIDER_MIN, min(_SLIDER_MAX, round(share * 0.3)))
        for category, share in weights.items()
    }


def _slider_values_for_profile(profile: UserProfile) -> dict[str, int]:
    return weights_to_slider_values(compute_weights(profile))


def render_profile_form() -> None:
    """Render the profile form. On submit, compute starting weights for the
    given profile once and hand them to render_weight_sliders through the
    "pending_slider_weights" session_state key it already consumes. No
    st.rerun() is needed: this renders before the sliders in the same script
    run, so they consume the key later in this very run. That ordering is
    load-bearing -- keep this call above render_weight_sliders. After the
    apply the sliders are ordinary independent widgets again until the next
    submit.
    """
    st.write("**Tell us about your situation** (sets starting category weights)")
    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            age_group = st.selectbox(
                "Age group",
                options=list(AgeGroup),
                format_func=lambda a: a.value,
                index=list(AgeGroup).index(_BASELINE.age_group),
            )
            has_children = st.checkbox("I have children", value=_BASELINE.has_children)
            urgency = st.selectbox(
                "How urgently are you moving?",
                options=list(RelocationUrgency),
                format_func=lambda u: u.value.capitalize(),
                index=list(RelocationUrgency).index(_BASELINE.urgency),
            )
        with col2:
            budget = st.selectbox(
                "Budget",
                options=list(BudgetSensitivity),
                format_func=lambda b: b.value.capitalize(),
                index=list(BudgetSensitivity).index(_BASELINE.budget),
            )
            environment = st.selectbox(
                "Lifestyle preference",
                options=list(EnvironmentPreference),
                format_func=lambda e: e.value.capitalize(),
                index=list(EnvironmentPreference).index(_BASELINE.environment),
            )
        submitted = st.form_submit_button("Apply my profile")

    if submitted:
        profile = UserProfile(
            age_group=age_group,
            has_children=has_children,
            urgency=urgency,
            budget=budget,
            environment=environment,
        )
        st.session_state["pending_slider_weights"] = _slider_values_for_profile(profile)
