import subprocess
import sys

import pytest
from test_nlu_classifier import EVAL_SET

from buurtkompas.dashboard.nlu_form import (
    _describe,
    _level_display,
    _nothing_detected,
)
from buurtkompas.dashboard.profile_form import _slider_values_for_profile
from buurtkompas.nlu.classifier import AxisMatch, ClassificationResult, classify
from buurtkompas.weighting.engine import (
    AgeGroup,
    BudgetSensitivity,
    UserProfile,
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
