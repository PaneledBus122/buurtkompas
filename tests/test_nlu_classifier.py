"""Tests for the embedding-based axis classifier.

These load the real sentence-transformers model (downloaded once, ~90MB, then
cached by huggingface_hub), so they need network access on a cold cache. The
model is loaded once per test module, not per test.

The labeled sets below are the actual deliverable: the classifier is only as
good as its reference phrases and threshold, and these sets are how that is
measured. EVAL_SET was used while tuning the phrases/threshold. HELDOUT_SET
was written before any tuning and was not used to pick phrases, so it is the
better estimate of behavior on unseen text -- with two caveats: it shares an
author with the reference phrases, and a few phrases were reworded to avoid
sharing vocabulary with it. Both sets are small (2-10 mentioned cases per
axis), so treat single-axis numbers as coarse.
Do not copy sentences from either set into the reference phrases.
"""

import pytest

from buurtkompas.nlu import classifier
from buurtkompas.nlu.classifier import ClassificationResult, classify
from buurtkompas.weighting import engine
from buurtkompas.weighting.engine import (
    AgeGroup,
    BudgetSensitivity,
    EnvironmentPreference,
    RelocationUrgency,
    UserProfile,
)

AXES = ["age_group", "has_children", "urgency", "budget", "environment"]

# Minimum accuracy per axis over a labeled set, where "correct" means the
# right level, or None when the axis was not mentioned.
MIN_AXIS_ACCURACY = 0.80

# Accuracy alone is easy to game here (most cells are None, so a classifier
# that never answers scores highly), so also require it to actually find the
# axes that are mentioned, and to stay quiet on those that are not.
#
# Per-axis recall rests on only 2-10 mentioned cases, so a single miss moves
# it by 10-50 points: the per-axis bar is deliberately coarse (it tolerates
# the current misses on a very small sample) and the pooled bars, which
# average over every axis, carry the real signal.
MIN_MENTIONED_RECALL = 0.60
MAX_FALSE_POSITIVE_RATE = 0.10
MIN_POOLED_RECALL = 0.75
MAX_POOLED_FALSE_POSITIVE_RATE = 0.05

# text -> {axis: expected level}. Axes not listed must come back None.
LabeledSet = list[tuple[str, dict[str, object]]]

EVAL_SET: LabeledSet = [
    # single axis: age
    (
        "I'm 27 and just started my first real job in Eindhoven",
        {"age_group": AgeGroup.TWENTIES},
    ),
    ("We're both in our late thirties", {"age_group": AgeGroup.THIRTIES}),
    ("I turned 46 last month", {"age_group": AgeGroup.FORTIES}),
    ("I'm 52, and my partner and I are downsizing", {"age_group": AgeGroup.FIFTIES}),
    ("I'm 67 and recently stopped working", {"age_group": AgeGroup.SIXTIES}),
    ("I'm 81 and want to be near the hospital", {"age_group": AgeGroup.SEVENTIES_PLUS}),
    # single axis: children
    ("We have a 3-year-old and a newborn", {"has_children": True}),
    ("I need a school within walking distance for my daughter", {"has_children": True}),
    ("As a single dad I want a safe street for my son", {"has_children": True}),
    # single axis: urgency
    (
        "My new employer wants me to start next month so I have to find a place fast",
        {"urgency": RelocationUrgency.HIGH},
    ),
    (
        "There's no hurry, our lease runs for another two years",
        {"urgency": RelocationUrgency.LOW},
    ),
    ("I'd like to move in the next few months", {"urgency": RelocationUrgency.MEDIUM}),
    # single axis: budget
    ("I can't afford anything expensive", {"budget": BudgetSensitivity.TIGHT}),
    (
        "Price isn't really a limiting factor for us",
        {"budget": BudgetSensitivity.FLEXIBLE},
    ),
    (
        "We've got a reasonable but not unlimited budget",
        {"budget": BudgetSensitivity.MODERATE},
    ),
    # single axis: environment
    (
        "I want to walk to bars and restaurants in the evening",
        {"environment": EnvironmentPreference.URBAN},
    ),
    (
        "I'd love to wake up to fields and birdsong",
        {"environment": EnvironmentPreference.RURAL},
    ),
    (
        "City or village, either is fine with me",
        {"environment": EnvironmentPreference.MIXED},
    ),
    # several axes in one sentence
    (
        "I'm 34 with two young kids, and money is tight",
        {
            "age_group": AgeGroup.THIRTIES,
            "has_children": True,
            "budget": BudgetSensitivity.TIGHT,
        },
    ),
    (
        "I'm 29, starting a new job in a month, so I need to move quickly",
        {"age_group": AgeGroup.TWENTIES, "urgency": RelocationUrgency.HIGH},
    ),
    (
        "We're in our fifties and looking for somewhere peaceful in the countryside",
        {"age_group": AgeGroup.FIFTIES, "environment": EnvironmentPreference.RURAL},
    ),
    (
        "Just graduated, broke, and looking for something cheap near the center",
        {
            "age_group": AgeGroup.TWENTIES,
            "budget": BudgetSensitivity.TIGHT,
            "environment": EnvironmentPreference.URBAN,
        },
    ),
    # nothing axis-relevant: every axis must stay None
    ("I like a house with a big garden and blue shutters", {}),
    ("The weather has been terrible lately", {}),
    ("Can you show me the map of Veldhoven?", {}),
    ("I enjoy cooking and playing the guitar", {}),
    ("Three bedrooms and a garage would be ideal", {}),
    ("My favourite colour is green", {}),
    ("Hello", {}),
    ("asdf qwerty", {}),
    ("The apartment is 65 square metres", {}),
    ("I live at number 42 on the main road", {}),
    # Regression: generic first-person self-description that does NOT mention
    # children. It used to trip has_children through phrases shaped like
    # "I'm a mother of ..." / "I'm a single parent" / "we have two kids".
    (
        (
            "I am twenty-five years old and planning to find a job. "
            "I am looking for an apartment with good access to the city centre."
        ),
        {
            "age_group": AgeGroup.TWENTIES,
            "environment": EnvironmentPreference.URBAN,
        },
    ),
    ("I am twenty-three years old and single", {"age_group": AgeGroup.TWENTIES}),
    ("We are a young couple looking for our first apartment", {}),
    ("I am a nurse and I work night shifts at the hospital", {}),
]

HELDOUT_SET: LabeledSet = [
    (
        "I'm in my early twenties and share a flat with friends",
        {"age_group": AgeGroup.TWENTIES},
    ),
    ("I'm 41 and just got promoted", {"age_group": AgeGroup.FORTIES}),
    ("Our little ones start school next year", {"has_children": True}),
    ("I'm 73 and recently widowed", {"age_group": AgeGroup.SEVENTIES_PLUS}),
    (
        "I have to be in Eindhoven by the first of the month",
        {"urgency": RelocationUrgency.HIGH},
    ),
    (
        "We're saving every euro, so cheap rent is a must",
        {"budget": BudgetSensitivity.TIGHT},
    ),
    ("Cost is not a concern", {"budget": BudgetSensitivity.FLEXIBLE}),
    (
        "I want lively streets, cafes and nightlife on my doorstep",
        {"environment": EnvironmentPreference.URBAN},
    ),
    (
        "Somewhere with woods and open space around it, far from traffic",
        {"environment": EnvironmentPreference.RURAL},
    ),
    (
        "I'm 58, my wife and I love hiking, and we want a calm village",
        {"age_group": AgeGroup.FIFTIES, "environment": EnvironmentPreference.RURAL},
    ),
    (
        "Newly relocated for work, kids in tow, need housing this month",
        {"has_children": True, "urgency": RelocationUrgency.HIGH},
    ),
    (
        "I'm 31, no rush at all, and we can spend what we like",
        {
            "age_group": AgeGroup.THIRTIES,
            "urgency": RelocationUrgency.LOW,
            "budget": BudgetSensitivity.FLEXIBLE,
        },
    ),
    ("I like pizza with extra cheese", {}),
    ("How many people live in Eindhoven?", {}),
    ("The kitchen should have a dishwasher and plenty of light", {}),
]

# One unambiguous sentence per level, worded differently from the reference
# phrases: a smoke test that every level is reachable. These are not an
# unseen-data measurement -- gaps they exposed (spelled-out ages, "just
# browsing") were closed by adding general phrases to the reference set.
CLEAR_EXAMPLES = [
    ("age_group", "Now that I'm in my twenties I want my own place", AgeGroup.TWENTIES),
    ("age_group", "Turning fifty was a big milestone for me", AgeGroup.FIFTIES),
    ("age_group", "I am seventy-five years old", AgeGroup.SEVENTIES_PLUS),
    ("has_children", "My two kids go to primary school", True),
    ("urgency", "I must relocate as soon as possible", RelocationUrgency.HIGH),
    ("urgency", "We're only browsing, nothing is pressing", RelocationUrgency.LOW),
    ("budget", "We have very little money to spend on rent", BudgetSensitivity.TIGHT),
    ("budget", "We can pay whatever the right home costs", BudgetSensitivity.FLEXIBLE),
    (
        "environment",
        "I'd like a house in the middle of the city",
        EnvironmentPreference.URBAN,
    ),
    (
        "environment",
        "I want a quiet rural village surrounded by nature",
        EnvironmentPreference.RURAL,
    ),
]

IRRELEVANT_TEXTS = [text for text, expected in EVAL_SET + HELDOUT_SET if not expected]


def _classify_all(labeled: LabeledSet) -> dict[str, ClassificationResult]:
    return {text: classify(text) for text, _ in labeled}


def score(
    labeled: LabeledSet, results: dict[str, ClassificationResult]
) -> dict[str, dict]:
    """Per-axis accuracy, recall on mentioned axes, and false-positive rate."""
    report = {}
    totals = dict.fromkeys(
        ["mentioned", "mentioned_correct", "unmentioned", "false_positives"], 0
    )
    for axis in AXES:
        correct = mentioned = mentioned_correct = unmentioned = false_positives = 0
        for text, expected in labeled:
            got = getattr(results[text], axis).level
            want = expected.get(axis)
            correct += got == want
            if want is None:
                unmentioned += 1
                false_positives += got is not None
            else:
                mentioned += 1
                mentioned_correct += got == want
        report[axis] = {
            "accuracy": correct / len(labeled),
            "recall": mentioned_correct / mentioned if mentioned else None,
            "false_positive_rate": false_positives / unmentioned
            if unmentioned
            else None,
            "mentioned": mentioned,
        }
        for key, value in [
            ("mentioned", mentioned),
            ("mentioned_correct", mentioned_correct),
            ("unmentioned", unmentioned),
            ("false_positives", false_positives),
        ]:
            totals[key] += value
    report["pooled"] = {
        "recall": totals["mentioned_correct"] / totals["mentioned"],
        "false_positive_rate": totals["false_positives"] / totals["unmentioned"],
    }
    return report


@pytest.fixture(scope="module")
def eval_results():
    return _classify_all(EVAL_SET)


@pytest.fixture(scope="module")
def heldout_results():
    return _classify_all(HELDOUT_SET)


@pytest.fixture(scope="module", autouse=True)
def _loaded_model():
    """Load the model and reference embeddings once for the whole module."""
    classify("warm up")


def _assert_meets_bars(report):
    for axis in AXES:
        stats = report[axis]
        assert stats["accuracy"] >= MIN_AXIS_ACCURACY, (axis, stats)
        if stats["recall"] is not None:
            assert stats["recall"] >= MIN_MENTIONED_RECALL, (axis, stats)
        if stats["false_positive_rate"] is not None:
            assert stats["false_positive_rate"] <= MAX_FALSE_POSITIVE_RATE, (
                axis,
                stats,
            )
    pooled = report["pooled"]
    assert pooled["recall"] >= MIN_POOLED_RECALL, pooled
    assert pooled["false_positive_rate"] <= MAX_POOLED_FALSE_POSITIVE_RATE, pooled


def test_eval_set_meets_accuracy_bars(eval_results):
    _assert_meets_bars(score(EVAL_SET, eval_results))


def test_heldout_set_meets_accuracy_bars(heldout_results):
    _assert_meets_bars(score(HELDOUT_SET, heldout_results))


@pytest.mark.parametrize("text", IRRELEVANT_TEXTS)
def test_irrelevant_text_leaves_every_axis_unset(text):
    result = classify(text)

    for axis in AXES:
        match = getattr(result, axis)
        assert match.level is None, (axis, match)
        assert match.matched_phrase is None


@pytest.mark.parametrize(
    ("axis", "text", "expected"), CLEAR_EXAMPLES, ids=[c[1] for c in CLEAR_EXAMPLES]
)
def test_clear_examples_reach_every_level(axis, text, expected):
    match = getattr(classify(text), axis)

    assert match.level == expected, match
    assert match.matched_phrase is not None


# Generic self-description with no mention of children. Passing at 0.48 against
# a 0.50 threshold is luck: a slightly different wording tipped a real report
# over the line, so require a real margin, not just "None".
CHILDREN_MARGIN = 0.05
GENERIC_SELF_DESCRIPTIONS = [
    "I am twenty-five years old and planning to find a job",
    "I am twenty-five years old",
    "I am twenty-eight years old and I work in IT",
    "I am forty years old and I just got divorced",
    "I am single",
    "I am a teacher and I love cycling",
]


@pytest.mark.parametrize("text", GENERIC_SELF_DESCRIPTIONS)
def test_generic_self_description_stays_clear_of_the_children_threshold(text):
    match = classify(text).has_children

    assert match.level is None, match
    assert match.similarity <= classifier._DEFAULT_THRESHOLD - CHILDREN_MARGIN, match


def test_classify_is_deterministic():
    text = "I'm 34 with two young kids, and money is tight"

    assert classify(text) == classify(text)


def test_empty_or_blank_text_leaves_every_axis_unset():
    for text in ["", "   ", "\n"]:
        result = classify(text)
        assert all(getattr(result, axis).level is None for axis in AXES)


def test_threshold_is_a_single_knob_for_every_axis():
    text = "I'm 34 with two young kids, and money is tight"

    nothing = classify(text, threshold=1.01)
    everything = classify(text, threshold=-1.0)

    assert all(getattr(nothing, axis).level is None for axis in AXES)
    assert all(getattr(everything, axis).level is not None for axis in AXES)


def test_to_profile_fills_unmentioned_axes_with_defaults():
    result = classify("hello", threshold=1.01)

    assert result.to_profile() == UserProfile()


def test_to_profile_uses_classified_levels():
    profile = classify("I'm 34 with two young kids, and money is tight").to_profile()

    assert profile.has_children is True
    assert profile.budget == BudgetSensitivity.TIGHT


def test_axis_names_match_user_profile_fields():
    assert set(AXES) == set(UserProfile.__dataclass_fields__)
    assert list(classifier._AXES) == AXES


def test_axis_enums_are_the_engines_not_copies():
    assert classifier.AgeGroup is engine.AgeGroup
    assert classifier.RelocationUrgency is engine.RelocationUrgency
    assert classifier.BudgetSensitivity is engine.BudgetSensitivity
    assert classifier.EnvironmentPreference is engine.EnvironmentPreference


def test_every_engine_level_has_reference_phrases():
    assert set(classifier.AGE_EXAMPLES) == set(AgeGroup)
    assert set(classifier.URGENCY_EXAMPLES) == set(RelocationUrgency)
    assert set(classifier.BUDGET_EXAMPLES) == set(BudgetSensitivity)
    assert set(classifier.ENVIRONMENT_EXAMPLES) == set(EnvironmentPreference)
