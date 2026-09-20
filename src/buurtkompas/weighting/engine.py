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
