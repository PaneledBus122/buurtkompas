import pytest
from test_weighting import CATEGORY_ORDER

from buurtkompas.dashboard import persona_buttons
from buurtkompas.dashboard.app import CATEGORY_LABELS
from buurtkompas.dashboard.persona_buttons import (
    _ACTIVE_KEY,
    _APPLY_KEY,
    _CATEGORY_TITLES,
    _GAIN_AXES,
    _shared_gain_key,
    current_gains,
    leading_category_note,
    persona_weights,
    take_requested_weights,
)
from buurtkompas.dashboard.profile_form import weights_to_slider_values
from buurtkompas.weighting import engine
from buurtkompas.weighting.engine import EXTREME_PROFILES, AxisGains

DEFAULT_GAINS = dict.fromkeys(_GAIN_AXES, 1.0)


def _click_persona(state: dict, category: str) -> None:
    """What render_persona_buttons' button branch does: change which persona
    is active and request an apply. Must NOT touch any gain key."""
    state[_ACTIVE_KEY] = category
    state[_APPLY_KEY] = True


def _move_gain(state: dict, axis: str, value: float) -> None:
    """What a gain slider's on_change does."""
    state[_shared_gain_key(axis)] = value
    state[_APPLY_KEY] = True


def test_nothing_is_applied_until_a_persona_has_been_touched():
    state = {}

    assert take_requested_weights(state) is None
    assert state == {}


def test_nothing_is_applied_if_a_gain_moves_before_any_persona_is_active():
    state = {}
    _move_gain(state, "age", 1.5)

    assert take_requested_weights(state) is None


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


def test_clicking_a_persona_with_no_stored_gains_uses_the_defaults():
    state = {}
    _click_persona(state, "schools")

    assert take_requested_weights(state) == weights_to_slider_values(
        persona_weights("schools", DEFAULT_GAINS)
    )


def test_non_default_gains_change_the_result():
    state = {}
    _click_persona(state, "schools")
    _move_gain(state, "children", 0.0)

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
    state = {}
    _click_persona(state, "safety")

    assert take_requested_weights(state) is not None
    assert _APPLY_KEY not in state
    assert take_requested_weights(state) is None


def test_switching_persona_preserves_a_gain_moved_earlier():
    # The core regression Phase 6c exists to fix: Phase 6b reset each
    # persona's own gains to 1.0 on its button click, so switching personas
    # silently discarded whatever calibration was in progress. Verified to
    # actually catch that bug: reverting Step 1 (giving the click branch a
    # "reset this category's gains to default" line again) makes this fail,
    # since the second click would then force children back to 1.0.
    state = {}
    _click_persona(state, "schools")
    take_requested_weights(state)

    _move_gain(state, "children", 0.0)
    take_requested_weights(state)
    assert state[_shared_gain_key("children")] == 0.0

    _click_persona(state, "safety")
    result = take_requested_weights(state)

    assert state[_shared_gain_key("children")] == 0.0
    assert current_gains(state) == {**DEFAULT_GAINS, "children": 0.0}
    assert result == weights_to_slider_values(
        persona_weights("safety", {**DEFAULT_GAINS, "children": 0.0})
    )


def test_a_later_gain_move_applies_to_whichever_persona_is_now_active():
    state = {}
    _click_persona(state, "schools")
    take_requested_weights(state)
    _click_persona(state, "safety")
    take_requested_weights(state)

    _move_gain(state, "budget", 1.7)
    result = take_requested_weights(state)

    assert result == weights_to_slider_values(
        persona_weights("safety", {**DEFAULT_GAINS, "budget": 1.7})
    )


def test_current_gains_reads_the_stored_values_with_defaults_for_the_rest():
    state = {_shared_gain_key("budget"): 1.5}

    gains = current_gains(state)

    assert gains == {**DEFAULT_GAINS, "budget": 1.5}
    assert AxisGains(**gains).budget == 1.5


def test_the_gain_axes_are_exactly_the_engines_axis_gains_fields():
    assert set(_GAIN_AXES) == set(AxisGains.__dataclass_fields__)


def test_the_categories_come_from_the_engine_not_a_second_list():
    assert persona_buttons.EXTREME_PROFILES is engine.EXTREME_PROFILES
    assert list(_CATEGORY_TITLES) == list(EXTREME_PROFILES) == CATEGORY_ORDER


def test_category_titles_match_app_pys_real_category_labels():
    # Guards against the Phase 6b drift: _CATEGORY_TITLES had guessed values
    # ("Schools", "Area affluence") that never matched app.py's sidebar
    # ("Education", "Income"). Duplicated on purpose (importing app.py here
    # would be circular), so nothing catches a future edit to one side but
    # not the other except this test.
    assert _CATEGORY_TITLES == CATEGORY_LABELS


def test_income_gets_an_honest_note_at_default_gains():
    weights = persona_weights("income", DEFAULT_GAINS)

    note = leading_category_note("income", weights)

    assert note is not None
    assert "Amenities (30%)" in note
    assert "Income (23%)" in note
    assert "22%" in note and "15%" in note  # the base-weight head start


def test_every_other_category_needs_no_note_at_default_gains():
    for category in CATEGORY_ORDER:
        if category == "income":
            continue
        weights = persona_weights(category, DEFAULT_GAINS)
        assert leading_category_note(category, weights) is None, category


def test_the_note_follows_the_current_shared_gains_not_a_fixed_default():
    weights = persona_weights("schools", {**DEFAULT_GAINS, "children": 0.0})

    note = leading_category_note("schools", weights)

    assert note is not None
    assert "Safety (22%)" in note and "Education (19%)" in note


def test_the_note_is_checked_generically_for_any_category():
    # Not special-cased on the string "income": any category that is not on
    # top gets it, and a tie is not "above".
    below = {c: 10.0 for c in CATEGORY_ORDER} | {"safety": 30.0, "housing": 5.0}

    note = leading_category_note("housing", below)

    assert note is not None and "Safety (30%)" in note and "Housing (5%)" in note
    assert leading_category_note("safety", below) is None
    assert leading_category_note("schools", dict.fromkeys(CATEGORY_ORDER, 10.0)) is None


def test_captions_move_with_non_default_gains_not_just_at_the_baseline():
    baseline = persona_weights("schools", DEFAULT_GAINS)
    moved = persona_weights("schools", {**DEFAULT_GAINS, "environment": 0.0})

    assert moved["schools"] != pytest.approx(baseline["schools"])
