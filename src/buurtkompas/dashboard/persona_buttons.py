"""Temporary validation UI: six buttons, one per scoring category, that
each load the UserProfile mathematically proven (weighting/engine.py's
EXTREME_PROFILES) to maximize that category's starting weight. Below each
button, five sliders let the user independently scale that persona's five
AxisGains away from their 1.0 default, for manual calibration against
real-world judgment (e.g. "this neighbourhood fits the schools-extreme
type, but children should matter less here").

Coexists with nlu_form.py (unchanged) and temporarily replaces
profile_form.py in render_dashboard_page; profile_form.py itself is
untouched and may return.

Applying is a one-shot, like profile_form.py and nlu_form.py: clicking a
persona's button, or moving one of its gain sliders, requests an apply, and
that run hands the persona's weights to render_weight_sliders() through the
same pending_slider_weights key. It must NOT re-apply on every rerun:
doing so would snap the sidebar sliders back whenever anything reran (so
they could never be adjusted by hand) and would overwrite a free-text
result that landed in the same run. The other five panels keep their own
slider state without affecting the map until their button or a slider is
touched.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping

import streamlit as st

from buurtkompas.dashboard.profile_form import weights_to_slider_values
from buurtkompas.weighting.engine import (
    BASE_WEIGHTS,
    EXTREME_PROFILES,
    AxisGains,
    compute_weights,
    describe_profile,
)

_GAIN_AXES = ("age", "children", "urgency", "budget", "environment")
_GAIN_MIN, _GAIN_MAX, _GAIN_DEFAULT, _GAIN_STEP = 0.0, 2.0, 1.0, 0.1

_APPLY_KEY = "persona_apply"

# Display titles only: the categories themselves come from EXTREME_PROFILES.
# Duplicates the spirit of app.py's CATEGORY_LABELS rather than importing it
# (app.py imports this module, so importing back would be circular), with
# "Area affluence" for income because that is what the category measures.
_CATEGORY_TITLES = {
    "schools": "Schools",
    "amenities": "Amenities",
    "quiet_nature": "Quiet & nature",
    "housing": "Housing",
    "income": "Area affluence",
    "safety": "Safety",
}


def _gain_key(category: str, axis: str) -> str:
    return f"persona_gain_{category}_{axis}"


def _request_apply(category: str) -> None:
    st.session_state[_APPLY_KEY] = category


def persona_gains(state: Mapping, category: str) -> dict[str, float]:
    """The category's five gain values as currently held in `state`, with
    the 1.0 default for any not set yet."""
    return {
        axis: state.get(_gain_key(category, axis), _GAIN_DEFAULT) for axis in _GAIN_AXES
    }


def persona_weights(category: str, gains: Mapping[str, float]) -> dict[str, float]:
    """The full 0-100 weight breakdown of `category`'s extreme profile at
    the given gains."""
    return compute_weights(EXTREME_PROFILES[category], AxisGains(**gains))


def take_requested_weights(state: MutableMapping) -> dict[str, int] | None:
    """Consume a pending apply request from `state` and return the
    slider-ready weights for it, or None if no persona was touched this run.
    Takes the mapping as an argument (st.session_state in the app, a plain
    dict in tests) so it can be tested without Streamlit.
    """
    category = state.pop(_APPLY_KEY, None)
    if category is None:
        return None
    return weights_to_slider_values(
        persona_weights(category, persona_gains(state, category))
    )


def leading_category_note(category: str, weights: Mapping[str, float]) -> str | None:
    """A plain-language note when `category` is NOT the largest weight in
    `weights`, else None. Checked generically (not a special case for any
    category name): it is true for income today, and would appear for
    whichever category develops the same property if the delta tables change.

    States only facts that hold whatever the reason: the two resulting weights
    and the two base weights. (Today's reason for income: at its extreme,
    income and amenities gain the same 9 points in total, and amenities
    simply starts 7 points higher.)
    """
    others = {c: w for c, w in weights.items() if c != category}
    top = max(others, key=others.get)
    if others[top] <= weights[category]:
        return None
    title, top_title = _CATEGORY_TITLES[category], _CATEGORY_TITLES[top]
    return (
        f"Note: with the current gains, {top_title} ({others[top]:.0f}%) still "
        f"ends up above {title} ({weights[category]:.0f}%). In the base weights "
        f"{top_title} starts at {BASE_WEIGHTS[top]:.0f}% vs "
        f"{BASE_WEIGHTS[category]:.0f}% for {title}, and this combination does not "
        f"lift {title} enough to overtake it. That is how the model works, not "
        "an error."
    )


def render_persona_buttons() -> None:
    st.write("**Or load a category-maximizing extreme** (temporary validation UI)")
    for category, profile in EXTREME_PROFILES.items():
        title = _CATEGORY_TITLES[category]
        with st.expander(f"{title} extreme"):
            st.caption(describe_profile(profile))
            at_defaults = compute_weights(profile)
            st.caption(
                f"At default gains this sets {title} to {at_defaults[category]:.0f}%, "
                "the most any axis combination can give it."
            )

            # The gain widgets below are created after this check in the same
            # pass, so resetting their keys here is allowed (Streamlit only
            # forbids setting a widget's key after that widget exists).
            if st.button("Apply this persona", key=f"persona_button_{category}"):
                for axis in _GAIN_AXES:
                    st.session_state[_gain_key(category, axis)] = _GAIN_DEFAULT
                st.session_state[_APPLY_KEY] = category

            # After the button, so it reflects the gains as reset this run.
            note = leading_category_note(
                category,
                persona_weights(category, persona_gains(st.session_state, category)),
            )
            if note:
                st.caption(note)

            for axis in _GAIN_AXES:
                key = _gain_key(category, axis)
                st.session_state.setdefault(key, _GAIN_DEFAULT)
                st.slider(
                    axis.capitalize(),
                    min_value=_GAIN_MIN,
                    max_value=_GAIN_MAX,
                    step=_GAIN_STEP,
                    key=key,
                    on_change=_request_apply,
                    args=(category,),
                )

    weights = take_requested_weights(st.session_state)
    if weights is not None:
        st.session_state["pending_slider_weights"] = weights
