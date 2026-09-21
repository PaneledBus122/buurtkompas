import pytest
from test_weighting import CATEGORY_ORDER

from buurtkompas.dashboard import persona_buttons
from buurtkompas.dashboard.persona_buttons import (
    _APPLY_KEY,
    _CATEGORY_TITLES,
    _GAIN_AXES,
    _gain_key,
    leading_category_note,
    persona_gains,
    persona_weights,
    take_requested_weights,
)
from buurtkompas.dashboard.profile_form import weights_to_slider_values
from buurtkompas.weighting import engine
from buurtkompas.weighting.engine import EXTREME_PROFILES, AxisGains

DEFAULT_GAINS = dict.fromkeys(_GAIN_AXES, 1.0)


def test_nothing_is_applied_until_a_persona_has_been_touched():
    state = {}

    assert take_requested_weights(state) is None
    assert state == {}


def test_schools_at_default_gains_reproduces_the_phase_6a_breakdown():
    weights = persona_weights("schools", DEFAULT_GAINS)

    expected = {
        "schools": 24.0,
        "amenities": 19.2,
        "quiet_nature": 21.1,
        "housing": 10.6,
        "income": 3.0,
        "safety": 22.1,
    }
    for category, want in expected.items():
        assert weights[category] == pytest.approx(want, abs=0.1), category
    assert weights_to_slider_values(weights) == {
        "schools": 7,
        "amenities": 6,
        "quiet_nature": 6,
        "housing": 3,
        "income": 1,
        "safety": 7,
    }


def test_a_request_with_no_stored_gains_uses_the_defaults():
    state = {_APPLY_KEY: "schools"}

    assert take_requested_weights(state) == weights_to_slider_values(
        persona_weights("schools", DEFAULT_GAINS)
    )


def test_non_default_gains_change_the_result():
    state = {_APPLY_KEY: "schools", _gain_key("schools", "children"): 0.0}

    changed = take_requested_weights(state)

    # Children switched off: schools loses its +6 and income its -10.
    assert changed == {
        "schools": 6,
        "amenities": 6,
        "quiet_nature": 6,
        "housing": 3,
        "income": 3,
        "safety": 7,
    }
    assert changed != weights_to_slider_values(
        persona_weights("schools", DEFAULT_GAINS)
    )


def test_a_request_is_applied_once_not_on_every_rerun():
    # The regression this design exists for: re-applying on every run would
    # snap the sidebar sliders back after any manual change, and overwrite a
    # free-text result landing in the same run.
    state = {_APPLY_KEY: "safety"}

    assert take_requested_weights(state) is not None
    assert _APPLY_KEY not in state
    assert take_requested_weights(state) is None


def test_each_panels_gains_are_independent():
    state = {
        _APPLY_KEY: "schools",
        _gain_key("amenities", "age"): 2.0,  # another panel's slider
    }

    assert take_requested_weights(state) == weights_to_slider_values(
        persona_weights("schools", DEFAULT_GAINS)
    )
    assert persona_gains(state, "amenities")["age"] == 2.0
    assert persona_gains(state, "schools")["age"] == 1.0


def test_gains_are_read_from_the_stored_values():
    state = {_gain_key("housing", "budget"): 1.5}

    gains = persona_gains(state, "housing")

    assert gains == {**DEFAULT_GAINS, "budget": 1.5}
    assert AxisGains(**gains).budget == 1.5


def test_the_gain_axes_are_exactly_the_engines_axis_gains_fields():
    assert set(_GAIN_AXES) == set(AxisGains.__dataclass_fields__)


def test_the_categories_come_from_the_engine_not_a_second_list():
    assert persona_buttons.EXTREME_PROFILES is engine.EXTREME_PROFILES
    assert list(_CATEGORY_TITLES) == list(EXTREME_PROFILES) == CATEGORY_ORDER


def test_income_gets_an_honest_note_at_default_gains():
    weights = persona_weights("income", DEFAULT_GAINS)

    note = leading_category_note("income", weights)

    assert note is not None
    assert "Amenities (30%)" in note
    assert "Area affluence (23%)" in note
    assert "22%" in note and "15%" in note  # the base-weight head start


def test_every_other_category_needs_no_note_at_default_gains():
    for category in CATEGORY_ORDER:
        if category == "income":
            continue
        weights = persona_weights(category, DEFAULT_GAINS)
        assert leading_category_note(category, weights) is None, category


def test_the_note_follows_the_current_gains_not_a_fixed_category():
    weights = persona_weights("schools", {**DEFAULT_GAINS, "children": 0.0})

    note = leading_category_note("schools", weights)

    assert note is not None
    assert "Safety (22%)" in note and "Schools (19%)" in note


def test_the_note_is_checked_generically_for_any_category():
    # Not special-cased on the string "income": any category that is not on
    # top gets it, and a tie is not "above".
    below = {c: 10.0 for c in CATEGORY_ORDER} | {"safety": 30.0, "housing": 5.0}

    note = leading_category_note("housing", below)

    assert note is not None and "Safety (30%)" in note and "Housing (5%)" in note
    assert leading_category_note("safety", below) is None
    assert leading_category_note("schools", dict.fromkeys(CATEGORY_ORDER, 10.0)) is None
