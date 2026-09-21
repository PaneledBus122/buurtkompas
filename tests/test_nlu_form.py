import subprocess
import sys

import pytest
from test_nlu_classifier import EVAL_SET

from buurtkompas.dashboard.nlu_form import (
    _CATEGORY_LABELS,
    _describe,
    _describe_categories,
    _level_display,
    _nothing_detected,
    _nothing_matched,
    _slider_values,
    _summary_lines,
)
from buurtkompas.dashboard.profile_form import (
    _slider_values_for_profile,
    _weights_to_slider_values,
)
from buurtkompas.nlu.classifier import (
    AxisMatch,
    ClassificationResult,
    classify,
    detect_mentioned_categories,
)
from buurtkompas.weighting.engine import (
    BASE_WEIGHTS,
    AgeGroup,
    BudgetSensitivity,
    UserProfile,
    apply_category_mentions,
    compute_weights,
)

NOT_MENTIONED = AxisMatch(level=None, similarity=0.31, matched_phrase=None)


def _result(**overrides: AxisMatch) -> ClassificationResult:
    axes = dict.fromkeys(
        ["age_group", "has_children", "urgency", "budget", "environment"],
        NOT_MENTIONED,
    )
    axes.update(overrides)
    return ClassificationResult(**axes)


def test_describe_reports_a_detected_enum_axis_with_its_match():
    result = _result(
        budget=AxisMatch(
            level=BudgetSensitivity.TIGHT,
            similarity=0.8123,
            matched_phrase="money is tight right now",
        )
    )

    line = next(line for line in _describe(result) if line.startswith("Budget"))

    assert line == (
        'Budget: tight (matched "money is tight right now", similarity 0.81)'
    )


def test_describe_reports_the_children_bool_as_yes():
    result = _result(
        has_children=AxisMatch(
            level=True, similarity=0.66, matched_phrase="we have two kids"
        )
    )

    line = next(line for line in _describe(result) if line.startswith("Children"))

    assert line == 'Children: yes (matched "we have two kids", similarity 0.66)'


def test_describe_shows_the_real_default_for_axes_not_mentioned():
    lines = _describe(_result())

    assert lines == [
        "Age group: not mentioned — using default (30s)",
        "Children: not mentioned — using default (no)",
        "Urgency: not mentioned — using default (low)",
        "Budget: not mentioned — using default (moderate)",
        "Environment: not mentioned — using default (mixed)",
    ]


def test_describe_mixes_detected_and_default_axes_in_axis_order():
    result = _result(
        age_group=AxisMatch(
            level=AgeGroup.FORTIES, similarity=0.9, matched_phrase="I'm 44"
        )
    )

    lines = _describe(result)

    assert lines[0].startswith("Age group: 40s (matched")
    assert all("using default" in line for line in lines[1:])


def test_level_display_handles_both_shapes_of_level():
    assert _level_display(True) == "yes"
    assert _level_display(False) == "no"
    assert _level_display(AgeGroup.SEVENTIES_PLUS) == "70s+"


def test_nothing_detected_is_true_only_when_every_axis_is_none():
    assert _nothing_detected(_result()) is True
    assert (
        _nothing_detected(_result(has_children=AxisMatch(True, 0.7, "I have kids")))
        is False
    )


def test_classified_text_reaches_the_same_sliders_as_the_equivalent_profile():
    # Wiring check only: text -> classify -> to_profile -> slider values must
    # equal building that profile directly. Neither classifier accuracy nor
    # the engine is under test here.
    text, expected = next(
        (t, e)
        for t, e in EVAL_SET
        if t == "I'm 34 with two young kids, and money is tight"
    )
    profile = UserProfile(
        age_group=expected["age_group"],
        has_children=expected["has_children"],
        budget=expected["budget"],
    )

    assert _slider_values_for_profile(classify(text).to_profile()) == (
        _slider_values_for_profile(profile)
    )


@pytest.mark.parametrize(
    "module", ["buurtkompas.dashboard.nlu_form", "buurtkompas.dashboard.app"]
)
def test_importing_the_dashboard_does_not_load_torch_or_the_classifier(module):
    # The lazy import is the point of this design: page loads must not pay
    # for torch. Checked in a fresh interpreter, since this test process has
    # already imported the classifier.
    code = (
        f"import sys, {module}; "
        "print(sorted(m for m in ('torch', 'sentence_transformers', "
        "'buurtkompas.nlu.classifier') if m in sys.modules))"
    )

    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()

    assert out == "[]"


def test_describe_categories_says_nothing_when_no_category_was_named():
    assert _describe_categories(frozenset()) is None


def test_describe_categories_lists_the_named_ones_in_dashboard_order():
    line = _describe_categories(frozenset({"safety", "schools"}))

    assert line == "Also emphasized: Education, Safety"


def test_category_labels_match_the_dashboard_labels():
    from buurtkompas.dashboard.app import CATEGORY_LABELS

    assert _CATEGORY_LABELS == CATEGORY_LABELS
    assert list(_CATEGORY_LABELS) == list(BASE_WEIGHTS)


def test_summary_covers_both_mechanisms_and_adds_no_extra_line_when_unneeded():
    with_categories = _summary_lines(_result(), frozenset({"safety"}))
    without = _summary_lines(
        _result(has_children=AxisMatch(True, 0.7, "young kids")), frozenset()
    )

    assert with_categories[-1] == "Also emphasized: Safety"
    assert all("Also emphasized" not in line for line in without)


def test_nothing_matched_needs_both_mechanisms_to_come_up_empty():
    assert _nothing_matched(_result(), frozenset()) is True
    assert _nothing_matched(_result(), frozenset({"safety"})) is False
    assert (
        _nothing_matched(_result(has_children=AxisMatch(True, 0.7, "x")), frozenset())
        is False
    )
    assert _summary_lines(_result(), frozenset())[0].startswith("Nothing in your")


def test_a_category_alone_still_applies_weights():
    # No axis detected but a category named: apply the baseline plus the boost.
    sliders = _slider_values(UserProfile(), frozenset({"safety"}))

    assert sliders["safety"] > _slider_values(UserProfile(), frozenset())["safety"]


def test_one_text_gets_both_the_axis_effect_and_the_category_boost():
    text = "I'm 34 with two young kids and a safe neighbourhood matters a lot to me"
    result = classify(text)
    mentioned = detect_mentioned_categories(text)
    assert result.has_children.level is True
    assert "safety" in mentioned

    combined = _slider_values(result.to_profile(), mentioned)
    axis_only = _slider_values(result.to_profile(), frozenset())
    baseline = _slider_values(UserProfile(), frozenset())

    # The axis mechanism: kids push schools up (has_children's +6 to schools).
    assert combined["schools"] > baseline["schools"]
    # The category mechanism: naming safety pushes it beyond what the axes
    # alone give it.
    assert combined["safety"] > axis_only["safety"]
    # And it is exactly "profile weights, then the boost", nothing else.
    assert combined == _weights_to_slider_values(
        apply_category_mentions(compute_weights(result.to_profile()), mentioned)
    )
