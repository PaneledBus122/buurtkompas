"""Temporary validation UI: six buttons, one per scoring category, that
each load the UserProfile mathematically proven (weighting/engine.py's
EXTREME_PROFILES) to maximize that category's starting weight. One shared
set of five AxisGains sliders, below all six panels, lets the user scale
every persona's axes the same way while switching between them.

Coexists with nlu_form.py (unchanged) and temporarily replaces
profile_form.py in render_dashboard_page; profile_form.py itself is
untouched and may return.

The gains are shared, not per-persona: the real workflow is picking a real
neighbourhood, flipping between the six extremes, and adjusting the five
gains while comparing each persona's weights/map against that
neighbourhood's actual character -- which only works if the gains stay put
while the active persona changes. An earlier version gave each persona its
own five sliders, reset to 1.0 on every button click; that discarded
whatever calibration was in progress the moment a different persona was
tried. Clicking a persona button now only changes which profile is active,
never the gains.

Applying is still a one-shot, like profile_form.py and nlu_form.py:
clicking a persona's button, or moving a gain slider, requests an apply,
consumed once at the bottom of this function and handed to
render_weight_sliders() through the same pending_slider_weights key. It
must NOT re-apply on every rerun: doing so would snap the sidebar sliders
back whenever anything reran (so they could never be adjusted by hand) and
would overwrite a free-text result that landed in the same run.
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

_ACTIVE_KEY = "active_persona"
_APPLY_KEY = "persona_apply_requested"

# Display titles only: the categories themselves come from EXTREME_PROFILES.
# Duplicated from app.py's CATEGORY_LABELS rather than imported: app.py
# imports this module, so importing back would be circular (same reasoning
# profile_form.py already documents for its own duplicated slider constants).
# Keep this in sync with app.py by hand; test_persona_buttons.py guards it.
_CATEGORY_TITLES = {
    "schools": "Education",
    "amenities": "Amenities",
    "quiet_nature": "Quiet & Nature",
    "housing": "Housing",
    "income": "Income",
    "safety": "Safety",
}


def _shared_gain_key(axis: str) -> str:
    return f"persona_gain_{axis}"


def _request_apply(*_args: object) -> None:
    st.session_state[_APPLY_KEY] = True


def _reset_gains(*_args: object) -> None:
    """Callback for the reset button: snaps all five shared gains back to
    1.0 and requests a re-apply, so an already-active persona's displayed
    weights immediately reflect the reset rather than looking stale until
    some other control is touched.

    Must run via on_click, not a plain post-render `if st.button(...):`
    block: a callback runs and mutates session_state before the sliders
    are re-instantiated on the rerun it triggers, which is the only safe
    time to overwrite a widget's own session_state key. Doing this after
    the sliders for the current run have already been created raises
    StreamlitWidgetAlreadyInstantiatedError -- confirmed by trying the
    naive version live before switching to on_click.
    """
    for axis in _GAIN_AXES:
        st.session_state[_shared_gain_key(axis)] = _GAIN_DEFAULT
    st.session_state[_APPLY_KEY] = True


def current_gains(state: Mapping) -> dict[str, float]:
    """The five shared gain values as currently held in `state`, with the
    1.0 default for any not set yet."""
    return {
        axis: state.get(_shared_gain_key(axis), _GAIN_DEFAULT) for axis in _GAIN_AXES
    }


def persona_weights(category: str, gains: Mapping[str, float]) -> dict[str, float]:
    """The full 0-100 weight breakdown of `category`'s extreme profile at
    the given gains."""
    return compute_weights(EXTREME_PROFILES[category], AxisGains(**gains))


def take_requested_weights(state: MutableMapping) -> dict[str, int] | None:
    """Consume a pending apply request from `state` and return the
    slider-ready weights for whichever persona is active, or None if
    nothing was touched this run. Takes the mapping as an argument
    (st.session_state in the app, a plain dict in tests) so it can be
    tested without Streamlit.
    """
    if not state.pop(_APPLY_KEY, False):
        return None
    active = state.get(_ACTIVE_KEY)
    if active is None:
        return None
    return weights_to_slider_values(persona_weights(active, current_gains(state)))


def leading_category_note(category: str, weights: Mapping[str, float]) -> str | None:
    """A plain-language note when `category` is NOT the largest weight in
    `weights`, else None. Checked generically (not a special case for any
    category name): it is true for income at default gains today, and
    would appear for whichever category develops the same property as the
    shared gains move, or if the delta tables ever change.

    States only facts that hold whatever the reason: the two resulting
    weights and the two base weights.
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
    gains = current_gains(st.session_state)
    for category, profile in EXTREME_PROFILES.items():
        title = _CATEGORY_TITLES[category]
        with st.expander(f"{title} extreme"):
            st.caption(describe_profile(profile))
            weights = persona_weights(category, gains)
            st.caption(
                f"With the current gains this sets {title} to {weights[category]:.0f}%."
            )
            note = leading_category_note(category, weights)
            if note:
                st.caption(note)

            if st.button("Apply this persona", key=f"persona_button_{category}"):
                st.session_state[_ACTIVE_KEY] = category
                st.session_state[_APPLY_KEY] = True

    st.write("**Axis sensitivity** (shared across all six personas)")
    for axis in _GAIN_AXES:
        key = _shared_gain_key(axis)
        st.session_state.setdefault(key, _GAIN_DEFAULT)
        st.slider(
            axis.capitalize(),
            min_value=_GAIN_MIN,
            max_value=_GAIN_MAX,
            step=_GAIN_STEP,
            key=key,
            on_change=_request_apply,
        )
    st.button(
        "Reset gains to default",
        key="persona_gain_reset",
        on_click=_reset_gains,
    )

    weights = take_requested_weights(st.session_state)
    if weights is not None:
        st.session_state["pending_slider_weights"] = weights
