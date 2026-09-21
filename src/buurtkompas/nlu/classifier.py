"""Embedding-based free-text classifier for the five weighting-engine axes.

Uses sentence-transformers/all-MiniLM-L6-v2 (Apache 2.0) for few-shot
nearest-example classification: a handful of example phrases per axis level
are embedded once, the input text is embedded the same way, and cosine
similarity picks the level whose best-matching example is closest -- or None
("not mentioned") if nothing clears the similarity threshold. This module
only classifies; it never computes or adjusts weighting numbers -- those
always come from buurtkompas.weighting.engine.compute_weights().

No Streamlit and no network calls at inference time: the model runs locally
on CPU (weights are downloaded once, on first load).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from sentence_transformers import SentenceTransformer, util
from torch import Tensor

from buurtkompas.weighting.engine import (
    AgeGroup,
    BudgetSensitivity,
    EnvironmentPreference,
    RelocationUrgency,
    UserProfile,
)

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Clause boundaries: one embedding of a multi-clause sentence dilutes each
# clause's signal, so each clause is also embedded on its own (see _chunks).
_CLAUSE_SPLIT = re.compile(
    r"[.;!?,]|\b(?:and|but|so|while|because|with)\b", flags=re.IGNORECASE
)
_MIN_CLAUSE_WORDS = 1

# Cosine similarity below this means "the text doesn't clearly say anything
# about this axis" -- the axis is left at its default rather than guessed.
# 0.5 sits just above the highest similarity any axis-irrelevant sentence in
# tests/test_nlu_classifier.py reaches (~0.47) and below most true matches;
# re-check against that harness after changing the phrases or the model.
_DEFAULT_THRESHOLD = 0.5


# Reference phrases are deliberately single-axis and free of housing nouns: a
# phrase that also mentions another axis (an age phrase about teenage kids) or
# generic housing vocabulary makes unrelated text match the wrong axis.
#
# Ages get one short phrase per year because the model encodes digits poorly
# (a single "I'm 62" phrase pulls in 46 and 67 alike); with every year present,
# the exact digits of the input find their own phrase.
_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TENS = {
    2: "twenty",
    3: "thirty",
    4: "forty",
    5: "fifty",
    6: "sixty",
    7: "seventy",
    8: "eighty",
    9: "ninety",
}


def _spelled(age: int) -> str:
    tens, ones = divmod(age, 10)
    return f"{_TENS[tens]}-{_ONES[ones]}" if ones else _TENS[tens]


def _ages(first: int, last: int) -> list[str]:
    """ "I'm 27" and "I'm twenty-seven" for every age in the range, plus
    "I'm turning fifty" for round decades."""
    phrases = []
    for age in range(first, last + 1):
        phrases += [f"I'm {age}", f"I'm {_spelled(age)}"]
        if age % 10 == 0:
            phrases.append(f"I'm turning {_spelled(age)}")
    return phrases


AGE_EXAMPLES: dict[AgeGroup, list[str]] = {
    AgeGroup.TWENTIES: [
        "I'm in my twenties",
        "we're in our twenties",
        "I recently graduated from university",
        *_ages(20, 29),
    ],
    AgeGroup.THIRTIES: [
        "I'm in my thirties",
        "we're in our thirties",
        *_ages(30, 39),
    ],
    AgeGroup.FORTIES: [
        "I'm in my forties",
        "we're in our forties",
        *_ages(40, 49),
    ],
    AgeGroup.FIFTIES: [
        "I'm in my fifties",
        "we're in our fifties",
        *_ages(50, 59),
    ],
    AgeGroup.SIXTIES: [
        "I'm in my sixties",
        "we're in our sixties",
        "I have just retired",
        *_ages(60, 69),
    ],
    AgeGroup.SEVENTIES_PLUS: [
        "I'm in my seventies",
        "we're in our seventies",
        "I'm a senior citizen",
        *_ages(70, 99),
    ],
}

# has_children is boolean, and there's no natural set of phrases for
# "explicitly stated I have no children" that people volunteer unprompted --
# silence about children should mean "not mentioned", which already equals
# the default (False), not a confident "no". So this axis has a single level
# (True): it is a one-sided threshold check, not an argmax between two
# example sets.
# Phrases are deliberately concrete (young kids, a newborn, primary school)
# rather than short first-person scaffolds like "I have kids" or "I'm a mother
# of ...": those sit close to ANY short self-description clause ("I am twenty-five
# years old", "I am a nurse", "we are a young couple") and produced false
# positives, while phrases anchored on child-related nouns do not.
CHILDREN_EXAMPLES: list[str] = [
    "I have two young children at home",
    "I have three school-age kids",
    "I have a son and a daughter",
    "I'm raising two young kids",
    "young kids",
    "a newborn baby",
    "a toddler at home",
    "kids in primary school",
    "a good school for my child",
    "a safe place for children to grow up",
]

URGENCY_EXAMPLES: dict[RelocationUrgency, list[str]] = {
    RelocationUrgency.LOW: [
        "there is no hurry",
        "I'm not in any hurry to move",
        "I'm taking my time",
        "just casually looking around",
        "there is no pressure to move quickly",
        "just browsing for now",
    ],
    RelocationUrgency.MEDIUM: [
        "I'd like to have moved within a few months",
        "I want to move this year, but there's no big rush",
    ],
    RelocationUrgency.HIGH: [
        "I have to move as soon as possible",
        "it is very urgent",
        "I need to move immediately",
        "I must relocate within weeks",
    ],
}

BUDGET_EXAMPLES: dict[BudgetSensitivity, list[str]] = {
    BudgetSensitivity.TIGHT: [
        "I'm on a shoestring budget",
        "money is tight right now",
        "I have to watch every penny",
        "I have a low income",
        "I'm broke",
        "I can't afford much",
    ],
    BudgetSensitivity.MODERATE: [
        "I have an average budget",
        "a normal, reasonable budget",
        "I can spend a decent amount, but not a lot",
        "we're neither rich nor poor",
    ],
    BudgetSensitivity.FLEXIBLE: [
        "money is no object",
        "the price doesn't matter to me",
        "price is not a constraint",
        "prices are not an issue for us",
        "I don't have to worry about prices",
        "I have plenty of money",
        "I'm happy to pay extra",
        "we can pay whatever it takes",
    ],
}

ENVIRONMENT_EXAMPLES: dict[EnvironmentPreference, list[str]] = {
    EnvironmentPreference.URBAN: [
        "the buzz of city life",
        "the middle of the city",
        "going out to bars, restaurants and shops",
        "a vibrant city centre",
        "urban living",
        "living in or near the city centre",
    ],
    EnvironmentPreference.MIXED: [
        "a mix of city and countryside",
        "no strong preference between urban and rural",
        "either the city or the countryside is fine",
    ],
    EnvironmentPreference.RURAL: [
        "living in the countryside",
        "somewhere rural and peaceful",
        "peace and quiet in nature",
        "far away from the city",
        "the sounds and beauty of nature",
        "living close to nature",
    ],
}

Level = AgeGroup | bool | RelocationUrgency | BudgetSensitivity | EnvironmentPreference

# Axis name (a UserProfile field) -> {level: example phrases}.
_AXES: dict[str, dict[Level, list[str]]] = {
    "age_group": AGE_EXAMPLES,
    "has_children": {True: CHILDREN_EXAMPLES},
    "urgency": URGENCY_EXAMPLES,
    "budget": BUDGET_EXAMPLES,
    "environment": ENVIRONMENT_EXAMPLES,
}


@dataclass(frozen=True)
class AxisMatch:
    """One axis's classification result. `level` is None when nothing
    cleared the threshold -- meaning "not mentioned", not "confidently the
    default level". `similarity` is the best cosine similarity seen even
    when it fell short, which is what threshold tuning needs."""

    level: Level | None
    similarity: float
    matched_phrase: str | None


@dataclass(frozen=True)
class ClassificationResult:
    age_group: AxisMatch
    has_children: AxisMatch
    urgency: AxisMatch
    budget: AxisMatch
    environment: AxisMatch

    def to_profile(self) -> UserProfile:
        """A UserProfile with every classified axis filled in and every
        "not mentioned" axis left at UserProfile()'s default."""
        defaults = UserProfile()
        return UserProfile(
            **{
                axis: getattr(self, axis).level
                if getattr(self, axis).level is not None
                else getattr(defaults, axis)
                for axis in _AXES
            }
        )


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(_MODEL_NAME)


@lru_cache(maxsize=1)
def _reference_embeddings() -> dict[str, dict[Level, Tensor]]:
    """Embed every reference phrase once, keyed by axis then level. Cached
    because embedding is the expensive part and these phrases never change
    at runtime."""
    model = _get_model()
    return {
        axis: {
            level: model.encode(phrases, convert_to_tensor=True)
            for level, phrases in levels.items()
        }
        for axis, levels in _AXES.items()
    }


def _chunks(text: str) -> list[str]:
    """The whole text plus each clause of it with at least
    _MIN_CLAUSE_WORDS words, without duplicates."""
    clauses = [part.strip() for part in _CLAUSE_SPLIT.split(text)]
    chunks = [text.strip()]
    for clause in clauses:
        if len(clause.split()) >= _MIN_CLAUSE_WORDS and clause not in chunks:
            chunks.append(clause)
    return chunks


def _best_match(
    text_embeddings: Tensor,
    level_embeddings: dict[Level, Tensor],
    examples: dict[Level, list[str]],
    threshold: float,
) -> AxisMatch:
    """Argmax over levels: for each level, take the best (chunk, example
    phrase) similarity, then pick whichever level is best overall. Below
    `threshold` the axis counts as not mentioned.
    """
    best_level: Level | None = None
    best_score = -1.0
    best_phrase: str | None = None
    for level, embeddings in level_embeddings.items():
        scores = util.cos_sim(text_embeddings, embeddings)
        _, top_index = divmod(int(scores.argmax()), scores.shape[1])
        score = float(scores.max())
        if score > best_score:
            best_level, best_score, best_phrase = (
                level,
                score,
                examples[level][top_index],
            )
    if best_score < threshold:
        return AxisMatch(level=None, similarity=best_score, matched_phrase=None)
    return AxisMatch(
        level=best_level, similarity=best_score, matched_phrase=best_phrase
    )


def classify(
    text: str, *, threshold: float = _DEFAULT_THRESHOLD
) -> ClassificationResult:
    """Classify free text into the five weighting-engine axes. Any axis the
    text doesn't clearly address comes back with level=None -- callers
    should leave that field at UserProfile()'s default rather than treat
    None as a value (ClassificationResult.to_profile() does exactly that).
    """
    if not text.strip():
        empty = AxisMatch(level=None, similarity=0.0, matched_phrase=None)
        return ClassificationResult(empty, empty, empty, empty, empty)

    text_embeddings = _get_model().encode(_chunks(text), convert_to_tensor=True)
    references = _reference_embeddings()
    matches = {
        axis: _best_match(text_embeddings, references[axis], _AXES[axis], threshold)
        for axis in _AXES
    }
    return ClassificationResult(**matches)
