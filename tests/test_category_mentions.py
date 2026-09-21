"""Tests for explicit category-mention detection (classifier.py) and its
labeled evaluation sets.

Same discipline as test_nlu_classifier.py: MENTION_DEV was used while tuning
the reference phrases; MENTION_HELDOUT was written before any tuning and not
used to pick phrases (same author, small, so treat numbers as coarse). Do not
copy sentences from either set into CATEGORY_MENTION_EXAMPLES.

The point of this layer is "the user names a scoring category outright", which
is a different question from the 5-axis classifier's "which level of an axis
applies". The hardest negatives are therefore budget / affordability and other
axis-only sentences: they must NOT name housing or income (personal budget is
the budget axis's job, and counting it twice would double-count one signal).
"""

from pathlib import Path

import pytest
from test_nlu_classifier import IRRELEVANT_TEXTS

from buurtkompas.nlu import classifier
from buurtkompas.nlu.classifier import classify, detect_mentioned_categories
from buurtkompas.weighting.engine import BASE_WEIGHTS

CATEGORIES = list(BASE_WEIGHTS)

MIN_CATEGORY_ACCURACY = 0.80
MIN_CATEGORY_RECALL = 0.60
MAX_CATEGORY_FALSE_POSITIVE_RATE = 0.10
MIN_POOLED_RECALL = 0.75
MAX_POOLED_FALSE_POSITIVE_RATE = 0.05

# text -> the categories it explicitly names. Everything not listed must not
# be detected.
LabeledSet = list[tuple[str, frozenset[str]]]


def _labeled(*rows: tuple[str, set[str]]) -> LabeledSet:
    return [(text, frozenset(cats)) for text, cats in rows]


# Sentences that state facts about the person or their budget, but name no
# scoring category. Personal money talk must not become "housing"/"income".
BUDGET_TALK = [
    "I can't afford anything expensive",
    "We're looking for something affordable",
    "Price isn't a limiting factor for us",
    "I earn a modest salary and rent is my biggest expense",
    "My budget is tight so I need cheap rent",
    "I can afford somewhere nicer than my current place",
    "Money is no object, we just want the right home",
    "We've got a reasonable but not unlimited budget",
]

# Axis-only sentences (age, children, urgency, budget, environment, ...) with no
# category named. Taken from test_nlu_classifier's sets.
AXIS_ONLY_DEV = [
    "I'm 27 and just started my first real job in Eindhoven",
    "We're both in our late thirties",
    "I turned 46 last month",
    "I'm 67 and recently stopped working",
    "There's no hurry, our lease runs for another two years",
    "I'd like to move in the next few months",
    "We have a 3-year-old and a newborn",
    "I'm 34 with two young kids, and money is tight",
    "Just graduated, broke, and looking for something cheap near the center",
    "I'm 29, starting a new job in a month, so I need to move quickly",
]

MENTION_DEV: LabeledSet = _labeled(
    ("I want to be near a good primary school", {"schools"}),
    ("The school should be within walking distance", {"schools"}),
    ("Good schools nearby matter a lot to me", {"schools"}),
    ("I'd like a supermarket and a doctor close by", {"amenities"}),
    (
        "It should be convenient, with shops and a daycare in the neighbourhood",
        {"amenities"},
    ),
    ("Everyday facilities within walking distance are important", {"amenities"}),
    ("I'm looking for a quiet, green neighbourhood", {"quiet_nature"}),
    ("I want plenty of parks and nature around me", {"quiet_nature"}),
    ("Somewhere that isn't too built-up", {"quiet_nature"}),
    ("I care about the quality of the homes in the area", {"housing"}),
    (
        "I'd like a neighbourhood with mostly owned houses rather than rentals",
        {"housing"},
    ),
    ("The houses around there should be well kept", {"housing"}),
    ("I want to live in an affluent area", {"income"}),
    ("A well-off neighbourhood with wealthy residents", {"income"}),
    ("I prefer a neighbourhood where people earn good incomes", {"income"}),
    ("It has to be a safe neighbourhood", {"safety"}),
    ("I want to feel safe walking home at night", {"safety"}),
    ("Low crime is a priority for me", {"safety"}),
    (
        "I'm 34 with two young kids and a safe neighbourhood matters a lot to me",
        {"safety"},
    ),
    ("We want good schools nearby and a quiet green area", {"schools", "quiet_nature"}),
    ("A safe area with a supermarket around the corner", {"safety", "amenities"}),
    *[(text, set()) for text in BUDGET_TALK[:5] + AXIS_ONLY_DEV],
    *[(text, set()) for text in IRRELEVANT_TEXTS],
)

MENTION_HELDOUT: LabeledSet = _labeled(
    ("Are there any good schools around?", {"schools"}),
    ("I'd want shops and a GP nearby", {"amenities"}),
    ("Peace and quiet with lots of trees around", {"quiet_nature"}),
    ("I'm looking at homes that are in good condition", {"housing"}),
    ("A rich, upscale neighbourhood would be ideal", {"income"}),
    ("I don't want to worry about burglaries", {"safety"}),
    ("We want a safe place with schools close by", {"safety", "schools"}),
    *[(text, set()) for text in BUDGET_TALK[5:]],
    ("How many people live in Eindhoven?", set()),
    ("I like pizza with extra cheese", set()),
    ("The kitchen should have a dishwasher and plenty of light", set()),
    ("Cost is not a concern", set()),
    ("We're saving every euro, so cheap rent is a must", set()),
    ("I'm 73 and recently widowed", set()),
    ("I'm 31, no rush at all, and we can spend what we like", set()),
    ("I have to be in Eindhoven by the first of the month", set()),
)


def score(labeled: LabeledSet, detected: dict[str, frozenset[str]]) -> dict[str, dict]:
    """Per-category accuracy / recall / false-positive rate, plus pooled."""
    report = {}
    totals = dict.fromkeys(
        ["mentioned", "mentioned_correct", "unmentioned", "false_positives"], 0
    )
    for category in CATEGORIES:
        correct = mentioned = mentioned_correct = unmentioned = false_positives = 0
        for text, expected in labeled:
            got = category in detected[text]
            want = category in expected
            correct += got == want
            if want:
                mentioned += 1
                mentioned_correct += got
            else:
                unmentioned += 1
                false_positives += got
        report[category] = {
            "accuracy": correct / len(labeled),
            "recall": mentioned_correct / mentioned if mentioned else None,
            "false_positive_rate": false_positives / unmentioned,
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


def _detect_all(labeled: LabeledSet) -> dict[str, frozenset[str]]:
    return {text: detect_mentioned_categories(text) for text, _ in labeled}


@pytest.fixture(scope="module", autouse=True)
def _loaded_model():
    """Load the model and reference embeddings once for the whole module."""
    detect_mentioned_categories("warm up")


@pytest.fixture(scope="module")
def dev_detected():
    return _detect_all(MENTION_DEV)


@pytest.fixture(scope="module")
def heldout_detected():
    return _detect_all(MENTION_HELDOUT)


def _assert_meets_bars(report):
    for category in CATEGORIES:
        stats = report[category]
        assert stats["accuracy"] >= MIN_CATEGORY_ACCURACY, (category, stats)
        if stats["recall"] is not None:
            assert stats["recall"] >= MIN_CATEGORY_RECALL, (category, stats)
        assert stats["false_positive_rate"] <= MAX_CATEGORY_FALSE_POSITIVE_RATE, (
            category,
            stats,
        )
    pooled = report["pooled"]
    assert pooled["recall"] >= MIN_POOLED_RECALL, pooled
    assert pooled["false_positive_rate"] <= MAX_POOLED_FALSE_POSITIVE_RATE, pooled


def test_dev_set_meets_bars(dev_detected):
    _assert_meets_bars(score(MENTION_DEV, dev_detected))


def test_heldout_set_meets_bars(heldout_detected):
    _assert_meets_bars(score(MENTION_HELDOUT, heldout_detected))


@pytest.mark.parametrize("text", BUDGET_TALK)
def test_personal_budget_talk_does_not_name_housing_or_income(text):
    # The budget axis owns "I can't afford ..."; naming housing/income here too
    # would double-count one signal through two mechanisms.
    assert detect_mentioned_categories(text) == frozenset(), text


def test_one_text_can_trigger_both_the_axis_and_the_category_mechanism():
    text = "I'm 34 with two young kids and a safe neighbourhood matters a lot to me"

    assert classify(text).has_children.level is True
    assert "safety" in detect_mentioned_categories(text)


def test_several_categories_can_be_detected_independently():
    text = "We want good schools nearby and a quiet green area"

    assert detect_mentioned_categories(text) >= {"schools", "quiet_nature"}


def test_detection_is_deterministic():
    text = "A safe area with a supermarket around the corner"

    assert detect_mentioned_categories(text) == detect_mentioned_categories(text)


def test_blank_text_names_no_category():
    for text in ["", "   ", "\n"]:
        assert detect_mentioned_categories(text) == frozenset()


def test_threshold_is_respected():
    text = "It has to be a safe neighbourhood"

    assert detect_mentioned_categories(text, threshold=1.01) == frozenset()
    assert detect_mentioned_categories(text, threshold=-1.0) == frozenset(CATEGORIES)


def test_reference_phrases_cover_exactly_the_engine_categories():
    assert list(classifier.CATEGORY_MENTION_EXAMPLES) == CATEGORIES
    assert all(classifier.CATEGORY_MENTION_EXAMPLES.values())


def test_detection_shares_the_single_model_instance():
    detect_mentioned_categories("a safe neighbourhood")
    classify("I'm 34 with two young kids")

    # One SentenceTransformer for everything: exactly one load, one cached
    # instance, and one construction site in the module source.
    info = classifier._get_model.cache_info()
    assert info.currsize == 1
    assert info.misses == 1
    source = Path(classifier.__file__).read_text(encoding="utf-8")
    assert source.count("SentenceTransformer(") == 1
