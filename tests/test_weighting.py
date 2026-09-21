import itertools
import re

import pytest

from buurtkompas.weighting import engine
from buurtkompas.weighting.engine import (
    AGE_DELTAS,
    BASE_WEIGHTS,
    BUDGET_DELTAS,
    CATEGORY_MENTION_BOOST,
    CHILDREN_DELTAS,
    ENVIRONMENT_DELTAS,
    EXTREME_PROFILES,
    FLOOR,
    TOTAL,
    URGENCY_DELTAS,
    AgeGroup,
    AxisGains,
    BudgetSensitivity,
    EnvironmentPreference,
    RelocationUrgency,
    UserProfile,
    _floor_clip_and_renormalize,
    apply_category_mentions,
    compute_weights,
    describe_profile,
    extreme_profile_for,
)

CATEGORY_ORDER = list(BASE_WEIGHTS)

# The reference values were rounded to one decimal, so allow +/-0.1 inclusive;
# the epsilon only absorbs float error at exactly 0.1 (see FIFTIES persona).
PERSONA_TOLERANCE = 0.1 + 1e-9

# (age, has_children, urgency, budget) -> schools, amenities, quiet_nature,
# housing, income, safety. Environment is always MIXED, gains all 1.0.
#
# The FIFTIES/children/LOW/FLEXIBLE row lists income as 2.9: that figure came
# from clipping once and dividing by the total, which leaves income below
# FLOOR. The iterative helper pins it at exactly 3.0, which is within
# tolerance and satisfies the floor invariant.
PERSONAS = [
    (AgeGroup.TWENTIES, False, RelocationUrgency.HIGH, BudgetSensitivity.TIGHT)
    + ([7.9, 25.7, 3.0, 19.8, 22.8, 20.8],),
    (AgeGroup.THIRTIES, True, RelocationUrgency.LOW, BudgetSensitivity.MODERATE)
    + ([21.0, 23.0, 14.0, 16.0, 5.0, 21.0],),
    (AgeGroup.FORTIES, False, RelocationUrgency.LOW, BudgetSensitivity.FLEXIBLE)
    + ([18.0, 24.0, 18.0, 9.0, 10.0, 21.0],),
    (AgeGroup.FIFTIES, True, RelocationUrgency.LOW, BudgetSensitivity.FLEXIBLE)
    + ([21.6, 23.5, 19.6, 10.8, 2.9, 21.6],),
    (AgeGroup.SIXTIES, False, RelocationUrgency.LOW, BudgetSensitivity.FLEXIBLE)
    + ([14.0, 22.0, 21.0, 10.0, 11.0, 22.0],),
    (AgeGroup.SEVENTIES_PLUS, False, RelocationUrgency.LOW, BudgetSensitivity.TIGHT)
    + ([9.0, 15.0, 13.0, 23.0, 21.0, 19.0],),
    (AgeGroup.TWENTIES, False, RelocationUrgency.LOW, BudgetSensitivity.FLEXIBLE)
    + ([15.0, 28.0, 14.0, 8.0, 12.0, 23.0],),
    (AgeGroup.THIRTIES, False, RelocationUrgency.HIGH, BudgetSensitivity.TIGHT)
    + ([10.0, 23.0, 5.0, 21.0, 21.0, 20.0],),
    (AgeGroup.FORTIES, True, RelocationUrgency.MEDIUM, BudgetSensitivity.TIGHT)
    + ([18.0, 21.0, 9.0, 24.0, 10.0, 18.0],),
    (AgeGroup.FIFTIES, False, RelocationUrgency.HIGH, BudgetSensitivity.MODERATE)
    + ([12.0, 24.0, 11.0, 14.0, 17.0, 22.0],),
]

ALL_DELTA_ROWS = [
    (f"{table_name}[{level}]", row)
    for table_name, table in [
        ("age", AGE_DELTAS),
        ("children", CHILDREN_DELTAS),
        ("urgency", URGENCY_DELTAS),
        ("budget", BUDGET_DELTAS),
        ("environment", ENVIRONMENT_DELTAS),
    ]
    for level, row in table.items()
]


def _all_profiles():
    return [
        UserProfile(age, children, urgency, budget, environment)
        for age, children, urgency, budget, environment in itertools.product(
            AgeGroup,
            (False, True),
            RelocationUrgency,
            BudgetSensitivity,
            EnvironmentPreference,
        )
    ]


def test_category_names_match_dashboard_category_labels():
    from buurtkompas.dashboard.app import CATEGORY_LABELS

    assert CATEGORY_ORDER == list(CATEGORY_LABELS)


@pytest.mark.parametrize(
    ("name", "row"), ALL_DELTA_ROWS, ids=[n for n, _ in ALL_DELTA_ROWS]
)
def test_every_delta_row_covers_all_categories_and_sums_to_zero(name, row):
    assert list(row) == CATEGORY_ORDER
    assert sum(row.values()) == pytest.approx(0.0, abs=1e-12)


def test_default_profile_returns_base_weights_unchanged():
    assert compute_weights(UserProfile()) == BASE_WEIGHTS
    assert compute_weights() == BASE_WEIGHTS


@pytest.mark.parametrize(
    ("age", "children", "urgency", "budget", "expected"),
    PERSONAS,
    ids=[f"{p[0].value}-{p[1]}-{p[2].value}-{p[3].value}" for p in PERSONAS],
)
def test_reference_personas(age, children, urgency, budget, expected):
    weights = compute_weights(UserProfile(age, children, urgency, budget))

    for category, want in zip(CATEGORY_ORDER, expected, strict=True):
        assert abs(weights[category] - want) <= PERSONA_TOLERANCE, category


def test_all_324_profiles_sum_to_total_and_respect_floor():
    profiles = _all_profiles()
    assert len(profiles) == 6 * 2 * 3 * 3 * 3

    for profile in profiles:
        weights = compute_weights(profile)
        assert list(weights) == CATEGORY_ORDER
        assert sum(weights.values()) == pytest.approx(TOTAL, abs=1e-6), profile
        assert min(weights.values()) >= FLOOR - 1e-6, profile


def test_clip_helper_pins_multiple_categories_and_rescales_the_rest():
    raw = {
        "schools": 1.0,
        "amenities": 60.0,
        "quiet_nature": 2.0,
        "housing": 20.0,
        "income": 12.0,
        "safety": 5.0,
    }

    result = _floor_clip_and_renormalize(raw)

    assert sum(result.values()) == pytest.approx(TOTAL)
    assert min(result.values()) >= FLOOR - 1e-9
    assert result["schools"] == FLOOR
    assert result["quiet_nature"] == FLOOR
    # Order among the untouched categories is preserved by the shared rescale.
    assert result["amenities"] > result["housing"] > result["income"] > result["safety"]


def test_clip_helper_needs_a_second_pass_when_rescaling_pushes_another_below_floor():
    # quiet_nature (3.2) starts above the floor, but absorbing the schools
    # clip shrinks it to ~2.4, so only a second pass can pin it.
    raw = {
        "schools": -30.0,
        "amenities": 80.0,
        "quiet_nature": 3.2,
        "housing": 15.0,
        "income": 16.9,
        "safety": 14.9,
    }
    assert sum(raw.values()) == pytest.approx(TOTAL)

    result = _floor_clip_and_renormalize(raw)

    assert result["schools"] == FLOOR
    assert result["quiet_nature"] == FLOOR
    assert sum(result.values()) == pytest.approx(TOTAL)
    assert min(result.values()) >= FLOOR - 1e-9


def test_clip_helper_leaves_input_without_violations_unchanged():
    assert _floor_clip_and_renormalize(dict(BASE_WEIGHTS)) == BASE_WEIGHTS


def test_clip_helper_raises_when_it_cannot_converge(monkeypatch):
    monkeypatch.setattr(engine, "_MAX_CLIP_ITERATIONS", 1)
    raw = {
        "schools": -30.0,
        "amenities": 80.0,
        "quiet_nature": 3.2,
        "housing": 15.0,
        "income": 16.9,
        "safety": 14.9,
    }

    with pytest.raises(RuntimeError, match="did not converge"):
        _floor_clip_and_renormalize(raw)


def test_all_zero_gains_reproduce_base_weights():
    profile = UserProfile(
        AgeGroup.SEVENTIES_PLUS,
        True,
        RelocationUrgency.HIGH,
        BudgetSensitivity.TIGHT,
        EnvironmentPreference.URBAN,
    )
    gains = AxisGains(age=0.0, children=0.0, urgency=0.0, budget=0.0, environment=0.0)

    assert compute_weights(profile, gains) == BASE_WEIGHTS


def test_doubling_a_gain_doubles_that_axis_contribution():
    # FORTIES is +1 on schools and no other axis moves; nothing clips.
    profile = UserProfile(age_group=AgeGroup.FORTIES)

    normal = compute_weights(profile)["schools"] - BASE_WEIGHTS["schools"]
    doubled = (
        compute_weights(profile, AxisGains(age=2.0))["schools"]
        - BASE_WEIGHTS["schools"]
    )

    assert normal == pytest.approx(1.0)
    assert doubled == pytest.approx(2 * normal)


def test_environment_axis_shifts_weight_between_amenities_and_quiet_nature():
    urban = compute_weights(UserProfile(environment=EnvironmentPreference.URBAN))
    rural = compute_weights(UserProfile(environment=EnvironmentPreference.RURAL))

    assert urban["amenities"] > BASE_WEIGHTS["amenities"] > rural["amenities"]
    assert urban["quiet_nature"] < BASE_WEIGHTS["quiet_nature"] < rural["quiet_nature"]


def _all_mention_sets():
    return [
        frozenset(c for i, c in enumerate(CATEGORY_ORDER) if mask >> i & 1)
        for mask in range(2 ** len(CATEGORY_ORDER))
    ]


def test_no_mentions_returns_the_weights_unchanged():
    weights = compute_weights(UserProfile(has_children=True))

    assert apply_category_mentions(weights, frozenset()) == weights


def test_a_single_mention_adds_exactly_the_boost_when_nothing_clips():
    weights = compute_weights()  # BASE_WEIGHTS

    boosted = apply_category_mentions(weights, frozenset({"safety"}))

    assert boosted["safety"] == pytest.approx(
        weights["safety"] + CATEGORY_MENTION_BOOST
    )
    # The points come proportionally from the other five, so their relative
    # proportions are unchanged.
    others = [c for c in CATEGORY_ORDER if c != "safety"]
    reference = others[0]
    for category in others:
        assert boosted[category] / boosted[reference] == pytest.approx(
            weights[category] / weights[reference]
        )


def test_every_profile_and_mention_combination_sums_to_total_and_respects_floor():
    mention_sets = _all_mention_sets()
    assert len(mention_sets) == 64

    for profile in _all_profiles():
        weights = compute_weights(profile)
        for mentioned in mention_sets:
            boosted = apply_category_mentions(weights, mentioned)
            assert list(boosted) == CATEGORY_ORDER
            assert sum(boosted.values()) == pytest.approx(TOTAL, abs=1e-6), (
                profile,
                mentioned,
            )
            assert min(boosted.values()) >= FLOOR - 1e-6, (profile, mentioned)


def test_a_single_mention_raises_that_category_for_every_profile():
    for profile in _all_profiles():
        weights = compute_weights(profile)
        for category in CATEGORY_ORDER:
            boosted = apply_category_mentions(weights, frozenset({category}))
            assert boosted[category] > weights[category], (profile, category)


def test_mentioning_a_category_the_axes_already_favour_pushes_it_further():
    # has_children already adds +6 to schools; naming schools adds the boost on top.
    weights = compute_weights(UserProfile(has_children=True))

    boosted = apply_category_mentions(weights, frozenset({"schools"}))

    assert weights["schools"] > BASE_WEIGHTS["schools"]
    assert boosted["schools"] > weights["schools"]


def test_mentioning_every_category_leaves_the_weights_unchanged():
    weights = compute_weights(UserProfile(has_children=True))

    assert apply_category_mentions(weights, frozenset(CATEGORY_ORDER)) == weights


def test_mentions_do_not_mutate_the_input():
    weights = compute_weights()
    before = dict(weights)

    apply_category_mentions(weights, frozenset({"safety", "schools"}))

    assert weights == before


def test_an_unknown_category_is_rejected_not_silently_dropped():
    with pytest.raises(ValueError, match=re.escape("Unknown categories: ['nonsense']")):
        apply_category_mentions(compute_weights(), frozenset({"safety", "nonsense"}))


def test_the_clip_helper_alone_does_not_fix_a_total_above_100():
    # Why apply_category_mentions is zero-sum instead of "+boost, then clip":
    # with every value at or above FLOOR the helper returns its input as is.
    weights = compute_weights()
    boosted = dict(weights)
    boosted["safety"] += CATEGORY_MENTION_BOOST

    assert sum(_floor_clip_and_renormalize(boosted).values()) == pytest.approx(
        TOTAL + CATEGORY_MENTION_BOOST
    )


# --- Category-maximizing ("extreme") profiles -------------------------------

# Categories whose extreme profile also makes them the largest weight. Income is
# the exception: at its own extreme, income and amenities gain the same 9
# points in total (amenities gains more from age, urgency and environment,
# income more from the tight budget), so amenities' 7-point head start in
# BASE_WEIGHTS decides it and amenities is still the top category.
TOPS_THE_RANKING = ["schools", "amenities", "quiet_nature", "housing", "safety"]


def test_extreme_profiles_cover_exactly_the_base_weight_categories():
    assert list(EXTREME_PROFILES) == CATEGORY_ORDER
    assert EXTREME_PROFILES == {c: extreme_profile_for(c) for c in CATEGORY_ORDER}


@pytest.mark.parametrize("category", CATEGORY_ORDER)
def test_extreme_profile_reaches_the_highest_weight_any_profile_can_give(category):
    # The real meaning of "maximizing": nothing among all 324 profiles beats it.
    # This also checks that choosing each axis independently is exact, i.e.
    # that floor-clipping never makes a lower raw value end up higher.
    best_possible = max(compute_weights(p)[category] for p in _all_profiles())

    reached = compute_weights(EXTREME_PROFILES[category])[category]

    assert reached == pytest.approx(best_possible, abs=1e-9)


@pytest.mark.parametrize("category", TOPS_THE_RANKING)
def test_extreme_profile_makes_the_category_the_strict_maximum(category):
    weights = compute_weights(EXTREME_PROFILES[category])

    others = [w for c, w in weights.items() if c != category]
    assert weights[category] > max(others)


def test_income_cannot_be_pushed_above_amenities_even_at_its_extreme():
    # Pinned on purpose: a UI that promises an "income" persona must know that
    # its breakdown is still amenities-led. If the delta tables change so this
    # flips, update this test and the UI copy together.
    weights = compute_weights(EXTREME_PROFILES["income"])

    assert weights["amenities"] > weights["income"]
    assert weights["income"] > weights["schools"]


def test_schools_extreme_profile_regression():
    profile = EXTREME_PROFILES["schools"]

    assert profile == UserProfile(
        AgeGroup.FORTIES,
        True,
        RelocationUrgency.LOW,
        BudgetSensitivity.FLEXIBLE,
        EnvironmentPreference.RURAL,
    )
    weights = compute_weights(profile)
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
    assert weights["income"] == FLOOR  # raw -1, clipped up to the floor


def test_housing_extreme_profile_regression_and_tie_break():
    profile = EXTREME_PROFILES["housing"]

    # 50s and 60s tie on housing (+1 each), and LOW and MEDIUM tie (0 each):
    # the first level in each table wins.
    assert (
        AGE_DELTAS[AgeGroup.FIFTIES]["housing"]
        == AGE_DELTAS[AgeGroup.SIXTIES]["housing"]
    )
    assert (
        URGENCY_DELTAS[RelocationUrgency.LOW]["housing"]
        == URGENCY_DELTAS[RelocationUrgency.MEDIUM]["housing"]
    )
    assert profile == UserProfile(
        AgeGroup.FIFTIES,
        True,
        RelocationUrgency.LOW,
        BudgetSensitivity.TIGHT,
        EnvironmentPreference.RURAL,
    )
    weights = compute_weights(profile)
    expected = {
        "schools": 18.0,
        "amenities": 13.0,
        "quiet_nature": 15.0,
        "housing": 26.0,
        "income": 10.0,
        "safety": 18.0,
    }
    for category, want in expected.items():
        assert weights[category] == pytest.approx(want, abs=0.1), category


def test_tied_profiles_agree_on_the_target_but_not_on_the_rest():
    tied = UserProfile(
        AgeGroup.SIXTIES,
        True,
        RelocationUrgency.LOW,
        BudgetSensitivity.TIGHT,
        EnvironmentPreference.RURAL,
    )
    chosen = compute_weights(EXTREME_PROFILES["housing"])
    other = compute_weights(tied)

    assert other["housing"] == pytest.approx(chosen["housing"])
    assert other["schools"] != pytest.approx(chosen["schools"])


def test_extreme_profile_for_an_unknown_category_is_rejected():
    with pytest.raises(ValueError, match="Unknown category: 'nonsense'"):
        extreme_profile_for("nonsense")


def test_describe_profile_for_the_baseline():
    assert describe_profile(UserProfile()) == (
        "30s · no children · low urgency · moderate budget · mixed"
    )


def test_describe_profile_for_a_profile_with_children():
    profile = UserProfile(
        AgeGroup.FORTIES,
        True,
        RelocationUrgency.LOW,
        BudgetSensitivity.FLEXIBLE,
        EnvironmentPreference.RURAL,
    )

    assert describe_profile(profile) == (
        "40s · has children · low urgency · flexible budget · rural"
    )


def test_describe_profile_for_a_profile_without_children():
    profile = UserProfile(
        AgeGroup.SEVENTIES_PLUS,
        False,
        RelocationUrgency.HIGH,
        BudgetSensitivity.TIGHT,
        EnvironmentPreference.URBAN,
    )

    assert describe_profile(profile) == (
        "70s+ · no children · high urgency · tight budget · urban"
    )


def test_every_extreme_profile_has_its_own_description():
    descriptions = [describe_profile(p) for p in EXTREME_PROFILES.values()]

    assert len(set(descriptions)) == len(descriptions)
