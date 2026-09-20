import pytest
from test_weighting import CATEGORY_ORDER, PERSONAS

from buurtkompas.dashboard.profile_form import (
    _slider_values_for_profile,
    _weights_to_slider_values,
)
from buurtkompas.weighting.engine import (
    FLOOR,
    AgeGroup,
    BudgetSensitivity,
    EnvironmentPreference,
    RelocationUrgency,
    UserProfile,
)


def test_equal_weights_map_to_equal_slider_values_in_range():
    weights = {c: 100 / 6 for c in CATEGORY_ORDER}

    values = _weights_to_slider_values(weights)

    assert set(values.values()) == {5}
    assert all(0 <= v <= 10 for v in values.values())


def test_extreme_weights_clip_into_slider_range_at_both_ends():
    weights = {
        "schools": FLOOR,
        "amenities": 100 - FLOOR - 5,
        "quiet_nature": 0.0,
        "housing": -5.0,
        "income": 1.0,
        "safety": 1.0,
    }

    values = _weights_to_slider_values(weights)

    assert values["amenities"] == 10
    assert values["quiet_nature"] == 0
    assert values["housing"] == 0
    assert all(0 <= v <= 10 for v in values.values())


def test_slider_values_keep_exactly_the_input_keys():
    weights = dict.fromkeys(CATEGORY_ORDER, 100 / 6)

    assert list(_weights_to_slider_values(weights)) == CATEGORY_ORDER


def test_default_profile_maps_to_the_baseline_slider_state():
    # BASE_WEIGHTS 15/22/13/15/15/20 x 0.3, rounded (4.5 rounds to 4).
    expected = dict(
        zip(CATEGORY_ORDER, [4, 7, 4, 4, 4, 6], strict=True),
    )

    assert _slider_values_for_profile(UserProfile()) == expected


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("age_group", AgeGroup.FORTIES, [5, 6, 4, 4, 4, 6]),
        ("has_children", True, [6, 7, 4, 5, 2, 6]),
        ("urgency", RelocationUrgency.HIGH, [4, 8, 3, 4, 5, 7]),
        ("budget", BudgetSensitivity.TIGHT, [4, 6, 3, 7, 6, 5]),
        ("environment", EnvironmentPreference.URBAN, [4, 8, 3, 4, 5, 6]),
        ("environment", EnvironmentPreference.RURAL, [5, 5, 5, 5, 4, 6]),
    ],
)
def test_each_form_field_reaches_the_right_axis(field, value, expected):
    # Expected values are hand-derived from the axis delta tables, so this
    # catches a field wired to the wrong axis without re-running the engine.
    profile = UserProfile(**{field: value})

    assert _slider_values_for_profile(profile) == dict(
        zip(CATEGORY_ORDER, expected, strict=True)
    )


@pytest.mark.parametrize(
    ("age", "children", "urgency", "budget", "expected_weights"),
    PERSONAS,
    ids=[f"{p[0].value}-{p[1]}-{p[2].value}-{p[3].value}" for p in PERSONAS],
)
def test_reference_personas_map_to_slider_values(
    age, children, urgency, budget, expected_weights
):
    profile = UserProfile(age, children, urgency, budget)

    assert _slider_values_for_profile(profile) == _weights_to_slider_values(
        dict(zip(CATEGORY_ORDER, expected_weights, strict=True))
    )
