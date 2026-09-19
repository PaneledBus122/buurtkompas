import pytest

from buurtkompas.dashboard.persona_presets import (
    CATEGORIES,
    PERSONAS,
    compute_weights,
)


@pytest.mark.parametrize(
    ("axes", "expected"),
    [
        (("20s", "no", "high", "tight"), [7.9, 25.7, 3.0, 19.8, 22.8, 20.8]),
        (("30s", "yes", "low", "moderate"), [21.0, 23.0, 14.0, 16.0, 5.0, 21.0]),
        (("40s", "no", "low", "flexible"), [18.0, 24.0, 18.0, 9.0, 10.0, 21.0]),
    ],
)
def test_compute_weights_matches_precomputed(axes, expected):
    weights = compute_weights(*axes)
    assert [weights[c] for c in CATEGORIES] == pytest.approx(expected, abs=0.05)


def test_every_persona_sums_to_100_and_respects_floor():
    for _label, _tooltip, *axes in PERSONAS:
        weights = compute_weights(*axes)
        assert sum(weights.values()) == pytest.approx(100)
        assert all(w > 0 for w in weights.values())
