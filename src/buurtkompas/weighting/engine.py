"""Deterministic category-weighting engine: maps a user's situation (age,
children, relocation urgency, budget, environment preference) to a starting
weight per scoring category, as percentage points summing to 100.

Pure computation: no Streamlit, no database, no I/O. The category names are
the keys of BASE_WEIGHTS (kept in sync with the dashboard's CATEGORY_LABELS
by a test, since importing the Streamlit entrypoint here would give this
package a UI dependency).

Each axis contributes an additive, reference-level-coded delta over
BASE_WEIGHTS: one level per axis has an all-zero row (the level baked into
BASE_WEIGHTS) and every row sums to zero, so an axis only redistributes
weight between categories and never changes the total. The axes are assumed
independent (no interaction terms), a documented simplification rather than
an empirically validated one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgeGroup(str, Enum):
    TWENTIES = "20s"
    THIRTIES = "30s"
    FORTIES = "40s"
    FIFTIES = "50s"
    SIXTIES = "60s"
    SEVENTIES_PLUS = "70s+"


class RelocationUrgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class BudgetSensitivity(str, Enum):
    TIGHT = "tight"
    MODERATE = "moderate"
    FLEXIBLE = "flexible"


class EnvironmentPreference(str, Enum):
    URBAN = "urban"
    MIXED = "mixed"
    RURAL = "rural"


@dataclass(frozen=True)
class UserProfile:
    """Defaults are the reference level of every axis, so UserProfile()
    yields exactly BASE_WEIGHTS."""

    age_group: AgeGroup = AgeGroup.THIRTIES
    has_children: bool = False
    urgency: RelocationUrgency = RelocationUrgency.LOW
    budget: BudgetSensitivity = BudgetSensitivity.MODERATE
    environment: EnvironmentPreference = EnvironmentPreference.MIXED


@dataclass(frozen=True)
class AxisGains:
    """Per-axis multiplier on that axis's deltas (1.0 = as tabulated, 0.0 =
    axis switched off)."""

    age: float = 1.0
    children: float = 1.0
    urgency: float = 1.0
    budget: float = 1.0
    environment: float = 1.0


# Reference combination: 30s / no children / low urgency / moderate budget /
# mixed environment. Amenities and safety highest, quiet_nature lowest,
# following the Leefbaarometer dimension weighting (voorzieningen and
# overlast/onveiligheid highest, fysieke omgeving lowest).
BASE_WEIGHTS: dict[str, float] = {
    "schools": 15.0,
    "amenities": 22.0,
    "quiet_nature": 13.0,
    "housing": 15.0,
    "income": 15.0,
    "safety": 20.0,
}

FLOOR = 3.0  # no category may end up below this, in percentage points
TOTAL = 100.0

_MAX_CLIP_ITERATIONS = 10

_ZERO: dict[str, float] = dict.fromkeys(BASE_WEIGHTS, 0.0)


def _row(
    schools: float,
    amenities: float,
    quiet_nature: float,
    housing: float,
    income: float,
    safety: float,
) -> dict[str, float]:
    return {
        "schools": schools,
        "amenities": amenities,
        "quiet_nature": quiet_nature,
        "housing": housing,
        "income": income,
        "safety": safety,
    }


AGE_DELTAS: dict[AgeGroup, dict[str, float]] = {
    AgeGroup.TWENTIES: _row(-2, 3, -3, -1, 2, 1),
    AgeGroup.THIRTIES: _ZERO,
    AgeGroup.FORTIES: _row(1, -1, 1, 0, 0, -1),
    AgeGroup.FIFTIES: _row(-1, -2, 2, 1, 1, -1),
    AgeGroup.SIXTIES: _row(-3, -3, 4, 1, 1, 0),
    AgeGroup.SEVENTIES_PLUS: _row(-3, -4, 4, 0, 1, 2),
}

CHILDREN_DELTAS: dict[bool, dict[str, float]] = {
    False: _ZERO,
    True: _row(6, 1, 1, 1, -10, 1),
}

URGENCY_DELTAS: dict[RelocationUrgency, dict[str, float]] = {
    RelocationUrgency.LOW: _ZERO,
    RelocationUrgency.MEDIUM: _row(-1, 2, -2, 0, 0, 1),
    RelocationUrgency.HIGH: _row(-2, 4, -4, -2, 1, 3),
}

BUDGET_DELTAS: dict[BudgetSensitivity, dict[str, float]] = {
    BudgetSensitivity.TIGHT: _row(-3, -3, -4, 8, 5, -3),
    BudgetSensitivity.MODERATE: _ZERO,
    BudgetSensitivity.FLEXIBLE: _row(2, 3, 4, -6, -5, 2),
}

ENVIRONMENT_DELTAS: dict[EnvironmentPreference, dict[str, float]] = {
    EnvironmentPreference.URBAN: _row(-1, 5, -3, -1, 1, -1),
    EnvironmentPreference.MIXED: _ZERO,
    EnvironmentPreference.RURAL: _row(1, -5, 3, 1, -1, 1),
}


def _floor_clip_and_renormalize(raw: dict[str, float]) -> dict[str, float]:
    """Raise every value below FLOOR to FLOOR, then rescale the rest so the
    total stays at TOTAL.

    Floor-clipping is needed because no category should ever be treated as
    worth (near) 0% of the decision, however extreme the combined axis
    adjustments. Clipping only ever pushes values up, so the total grows and
    the remaining categories must shrink proportionally to pay for it —
    that is the only reason renormalization is needed. It has to be iterative
    because that shrinkage can itself push a previously acceptable category
    below FLOOR; each pass pins the newly-too-small categories at FLOOR
    (permanently) and rescales the still-free ones, until none is below.
    """
    values = dict(raw)
    fixed: set[str] = set()

    for _ in range(_MAX_CLIP_ITERATIONS):
        newly_below = [c for c, v in values.items() if c not in fixed and v < FLOOR]
        if not newly_below:
            return values

        for category in newly_below:
            values[category] = FLOOR
            fixed.add(category)

        free = [c for c in values if c not in fixed]
        if not free:
            raise ValueError(
                f"Every category is pinned at the floor; weights cannot sum to {TOTAL}."
            )
        remaining_total = TOTAL - FLOOR * len(fixed)
        current_free_sum = sum(values[c] for c in free)
        if current_free_sum <= 0:
            # Defensive: free values are >= FLOOR > 0 on entry, so this is
            # not reachable from valid input.
            for category in free:
                values[category] = remaining_total / len(free)
        else:
            scale = remaining_total / current_free_sum
            for category in free:
                values[category] *= scale

    raise RuntimeError(
        f"Floor clipping did not converge within {_MAX_CLIP_ITERATIONS} "
        f"iterations for input {raw!r}."
    )


_DEFAULT_PROFILE = UserProfile()
_DEFAULT_GAINS = AxisGains()


def compute_weights(
    profile: UserProfile = _DEFAULT_PROFILE,
    gains: AxisGains = _DEFAULT_GAINS,
) -> dict[str, float]:
    """Starting category weights for `profile`, in percentage points that
    sum to 100, each at least FLOOR."""
    axis_terms = (
        (gains.age, AGE_DELTAS[profile.age_group]),
        (gains.children, CHILDREN_DELTAS[profile.has_children]),
        (gains.urgency, URGENCY_DELTAS[profile.urgency]),
        (gains.budget, BUDGET_DELTAS[profile.budget]),
        (gains.environment, ENVIRONMENT_DELTAS[profile.environment]),
    )
    raw = dict(BASE_WEIGHTS)
    for gain, deltas in axis_terms:
        for category in raw:
            raw[category] += gain * deltas[category]
    return _floor_clip_and_renormalize(raw)


# Percentage points added to each explicitly mentioned category. A starting
# heuristic, not derived from data: roughly the size of the largest single axis
# delta (budget's +8 to housing), on the reasoning that stating a category
# outright is at least as strong a signal as an indirect demographic
# correlation. One shared number, like the axis gains, not one per category.
CATEGORY_MENTION_BOOST = 10.0


def apply_category_mentions(
    weights: dict[str, float], mentioned: frozenset[str] | set[str]
) -> dict[str, float]:
    """Boost each explicitly mentioned category by CATEGORY_MENTION_BOOST
    points, taking those points proportionally from the categories that were
    not mentioned, so the total stays at TOTAL.

    Meant to run on compute_weights()'s output (which sums to TOTAL). It is
    zero-sum on purpose, like every axis delta row. Do not rely on
    _floor_clip_and_renormalize to fix the total for you: it only rescales
    when a value is below FLOOR, and returns an input whose values are all
    above FLOOR untouched, so a plain "+10 then clip" would come back summing
    to 110. It is still the final guard here, for the case where taking the
    points would push an unmentioned category under FLOOR.

    If every category is mentioned there is nothing to take from and the
    weights come back unchanged. Unknown category names raise ValueError
    instead of being silently dropped.
    """
    unknown = set(mentioned) - set(weights)
    if unknown:
        raise ValueError(f"Unknown categories: {sorted(unknown)}")
    others = [c for c in weights if c not in mentioned]
    if not mentioned or not others:
        return dict(weights)

    others_total = sum(weights[c] for c in others)
    keep = 1 - CATEGORY_MENTION_BOOST * len(mentioned) / others_total
    raw = {
        c: weights[c] + CATEGORY_MENTION_BOOST if c in mentioned else weights[c] * keep
        for c in weights
    }
    return _floor_clip_and_renormalize(raw)


def extreme_profile_for(category: str) -> UserProfile:
    """The UserProfile whose axis levels each individually maximize
    `category`'s delta, i.e. the profile that pushes that one category as high
    as compute_weights() can.

    Each axis is optimized independently and the model has no interaction
    terms (see the module docstring), so this is exact for the raw value, and
    a test brute-forces all 324 profiles to confirm it also gives the maximum
    final weight. It maximizes the category's weight, not its rank: no profile
    makes `income` outrank `amenities`, for example.

    Ties within one axis's column (age 50s vs 60s for `housing`, urgency LOW
    vs MEDIUM for `housing`) go to whichever level comes first in that axis's
    table: arbitrary but deterministic. The targeted category's weight is the
    same for tied levels, but every other category's is not, so do not treat
    tied profiles as interchangeable when showing the full breakdown.
    """
    if category not in BASE_WEIGHTS:
        raise ValueError(f"Unknown category: {category!r}")

    def best(deltas):
        return max(deltas, key=lambda level: deltas[level][category])

    return UserProfile(
        age_group=best(AGE_DELTAS),
        has_children=best(CHILDREN_DELTAS),
        urgency=best(URGENCY_DELTAS),
        budget=best(BUDGET_DELTAS),
        environment=best(ENVIRONMENT_DELTAS),
    )


# One ready-made profile per category, in BASE_WEIGHTS order, derived from the
# delta tables above (never re-typed anywhere else).
EXTREME_PROFILES: dict[str, UserProfile] = {
    category: extreme_profile_for(category) for category in BASE_WEIGHTS
}


def describe_profile(profile: UserProfile) -> str:
    """A short one-liner, e.g. '40s · has children · low urgency · flexible
    budget · rural'. Plain text, no UI dependency, for anywhere a UserProfile
    has to be shown to a user."""
    return " · ".join(
        [
            profile.age_group.value,
            "has children" if profile.has_children else "no children",
            f"{profile.urgency.value} urgency",
            f"{profile.budget.value} budget",
            profile.environment.value,
        ]
    )
