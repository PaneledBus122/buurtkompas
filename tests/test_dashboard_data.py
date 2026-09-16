"""Unit tests for the pure geometry/feature-collection transforms in
dashboard/data.py (fetch_* functions need a live DB and aren't covered here —
this targets the parts that don't).

Drop this module in ``tests/test_dashboard_data.py``.
"""

import math

import pandas as pd
import pytest

from buurtkompas.dashboard.data import (
    build_feature_collection,
    compute_overall_score,
    compute_view_state,
    merge_region_scores,
    scale_bar_widths,
)

ALL_CATEGORIES = ["schools", "amenities", "quiet_nature", "housing", "income", "safety"]


def _category_rows(region_id: str, gemeente_code: str, scores: dict[str, float | None]):
    """One fct_category_score-shaped row per (category, score) pair, with a
    None score representing a category that never cleared the
    coverage-threshold gate (a real NULL row from the mart's LEFT JOIN
    pattern), not a missing row.
    """
    return [
        {
            "region_id": region_id,
            "gemeente_code": gemeente_code,
            "category": category,
            "category_score": score,
        }
        for category, score in scores.items()
    ]


def _row(
    region_id: str, name: str, score: float | None, square: tuple[float, float]
) -> dict:
    """A minimal fake DB row: a 0.01deg x 0.01deg square Polygon at (lon, lat)."""
    lon, lat = square
    d = 0.01
    return {
        "region_id": region_id,
        "name": name,
        "category_score": score,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [lon, lat],
                    [lon + d, lat],
                    [lon + d, lat + d],
                    [lon, lat + d],
                    [lon, lat],
                ]
            ],
        },
    }


def test_build_feature_collection_preserves_region_count():
    rows = [
        _row("BU1", "Centrum", 0.8, (5.4, 51.4)),
        _row("BU2", "Strijp", None, (5.5, 51.5)),
    ]
    fc = build_feature_collection(rows)
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2


def test_build_feature_collection_labels_missing_score_as_na():
    rows = [_row("BU1", "Centrum", None, (5.4, 51.4))]
    fc = build_feature_collection(rows)
    props = fc["features"][0]["properties"]
    assert props["score_label"] == "N/A"
    assert props["category_score"] is None


def test_build_feature_collection_labels_real_score_as_two_decimals():
    rows = [_row("BU1", "Centrum", 0.8, (5.4, 51.4))]
    fc = build_feature_collection(rows)
    assert fc["features"][0]["properties"]["score_label"] == "0.80"


def test_compute_view_state_centers_on_bounding_box():
    rows = [_row("BU1", "A", 0.5, (5.0, 51.0)), _row("BU2", "B", 0.5, (5.2, 51.2))]
    fc = build_feature_collection(rows)
    view = compute_view_state(fc)
    # Two 0.01-degree squares at (5.0, 51.0) and (5.2, 51.2): bbox spans
    # roughly 5.0-5.21 lon, 51.0-51.21 lat, so the center should land near
    # the midpoint of those two square origins (within one square-width).
    assert 5.0 <= view["longitude"] <= 5.21
    assert 51.0 <= view["latitude"] <= 51.21
    assert 3.0 <= view["zoom"] <= 15.0


def test_compute_view_state_handles_empty_feature_collection():
    fc = {"type": "FeatureCollection", "features": []}
    view = compute_view_state(fc)
    # Falls back to a de-zoomed view of the Netherlands rather than raising
    # (e.g. ValueError from min() on an empty sequence).
    assert view["zoom"] < 10


def test_merge_region_scores_attaches_score_by_region_id():
    geometries = [
        {"region_id": "BU1", "name": "Centrum", "geometry": {"type": "Point"}},
        {"region_id": "BU2", "name": "Strijp", "geometry": {"type": "Point"}},
    ]
    scores = {"BU1": 0.8, "BU2": 0.2}

    rows = merge_region_scores(geometries, scores)

    assert rows[0]["category_score"] == 0.8
    assert rows[1]["category_score"] == 0.2
    assert rows[0]["name"] == "Centrum"


def test_merge_region_scores_defaults_missing_region_to_none():
    geometries = [{"region_id": "BU1", "name": "Centrum", "geometry": {}}]

    rows = merge_region_scores(geometries, {})

    assert rows[0]["category_score"] is None


def test_compute_overall_score_ranks_all_six_categories_present():
    weights = dict.fromkeys(ALL_CATEGORIES, 1 / 6)
    df = pd.DataFrame(
        _category_rows("BU_HIGH", "GM0772", dict.fromkeys(ALL_CATEGORIES, 0.9))
        + _category_rows("BU_LOW", "GM0772", dict.fromkeys(ALL_CATEGORIES, 0.1))
    )

    result = compute_overall_score(df, weights)

    # Two distinct composite values in one gemeente: the higher one is the
    # best (1.0), the lower one is the worst (0.5, since rank(pct=True)
    # with 2 values gives 1/2 and 2/2).
    assert result["BU_HIGH"] == 1.0
    assert result["BU_LOW"] == 0.5


def test_compute_overall_score_renormalizes_missing_categories():
    """A region missing its most heavily-weighted category must have that
    weight redistributed across the categories it does have — not simply
    dropped. Constructed so a buggy "drop the missing weight" (rather than
    renormalize) implementation would flip the expected ranking: BU_MISSING
    is missing the 0.7-weighted `schools` category entirely but scores a
    perfect 1.0 in every other category, so once its remaining weights are
    renormalized to sum to 1, its composite is trivially 1.0 (a weighted
    average of all-1.0s) -- higher than BU_FULL's mediocre 0.65, even
    though BU_MISSING is missing the single biggest-weighted category.
    A non-renormalizing implementation would instead compute BU_MISSING's
    raw composite as just 0.3 (the present weights' original, un-rescaled
    sum), which is lower than BU_FULL's 0.65 -- the opposite ranking.
    """
    weights = {
        "schools": 0.7,
        "amenities": 0.1,
        "quiet_nature": 0.1,
        "housing": 0.05,
        "income": 0.025,
        "safety": 0.025,
    }
    df = pd.DataFrame(
        _category_rows(
            "BU_FULL",
            "GM0772",
            {
                "schools": 0.5,
                "amenities": 1.0,
                "quiet_nature": 1.0,
                "housing": 1.0,
                "income": 1.0,
                "safety": 1.0,
            },
        )
        + _category_rows(
            "BU_MISSING",
            "GM0772",
            {
                "schools": None,  # never cleared the coverage threshold
                "amenities": 1.0,
                "quiet_nature": 1.0,
                "housing": 1.0,
                "income": 1.0,
                "safety": 1.0,
            },
        )
    )

    result = compute_overall_score(df, weights)

    assert result["BU_MISSING"] == 1.0
    assert result["BU_FULL"] == 0.5
    assert result["BU_MISSING"] > result["BU_FULL"]


def test_compute_overall_score_below_minimum_categories_is_nan():
    weights = dict.fromkeys(ALL_CATEGORIES, 1 / 6)
    df = pd.DataFrame(
        _category_rows("BU_ENOUGH", "GM0772", dict.fromkeys(ALL_CATEGORIES, 0.6))
        + _category_rows(
            "BU_TOO_FEW",
            "GM0772",
            {
                "schools": 0.8,
                "amenities": 0.7,
                "quiet_nature": None,
                "housing": None,
                "income": None,
                "safety": None,
            },
        )
    )

    result = compute_overall_score(df, weights)

    # Only 2 of 6 categories present, below MIN_CATEGORIES_FOR_OVERALL (3).
    assert math.isnan(result["BU_TOO_FEW"])
    # A region with enough categories elsewhere isn't affected by another
    # region falling below the threshold.
    assert not math.isnan(result["BU_ENOUGH"])


def test_compute_overall_score_zero_present_categories_is_nan():
    weights = dict.fromkeys(ALL_CATEGORIES, 1 / 6)
    df = pd.DataFrame(
        _category_rows("BU_ENOUGH", "GM0772", dict.fromkeys(ALL_CATEGORIES, 0.6))
        + _category_rows("BU_NONE", "GM0772", dict.fromkeys(ALL_CATEGORIES, None))
    )

    result = compute_overall_score(df, weights)

    assert math.isnan(result["BU_NONE"])


def test_compute_overall_score_equal_weights_matches_plain_average():
    """With equal weights and every category present, the weighted
    composite degenerates to a plain mean -- this cross-checks
    compute_overall_score's weighting/renormalization logic against the
    simplest possible independent computation of the same thing.
    """
    weights = dict.fromkeys(ALL_CATEGORIES, 1 / 6)
    scores_by_region = {
        "BU_A": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4],
        "BU_B": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "BU_C": [0.1, 0.2, 0.1, 0.2, 0.1, 0.2],
    }
    df = pd.DataFrame(
        [
            row
            for region_id, scores in scores_by_region.items()
            for row in _category_rows(
                region_id, "GM0772", dict(zip(ALL_CATEGORIES, scores))
            )
        ]
    )

    result = compute_overall_score(df, weights)

    expected_raw = {
        region_id: sum(scores) / len(scores)
        for region_id, scores in scores_by_region.items()
    }
    expected_rank = pd.Series(expected_raw).rank(pct=True)

    for region_id in scores_by_region:
        assert result[region_id] == pytest.approx(expected_rank[region_id])


def test_compute_overall_score_covers_every_input_region():
    """The returned Series always has an entry for every region_id in the
    input, including ones that end up NaN, so a caller can look up any
    region without a KeyError (matching merge_region_scores' own "always
    present, sometimes None" contract).
    """
    weights = dict.fromkeys(ALL_CATEGORIES, 1 / 6)
    df = pd.DataFrame(
        _category_rows("BU_A", "GM0772", dict.fromkeys(ALL_CATEGORIES, 0.6))
        + _category_rows("BU_B", "GM0772", dict.fromkeys(ALL_CATEGORIES, None))
    )

    result = compute_overall_score(df, weights)

    assert set(result.index) == {"BU_A", "BU_B"}


def test_build_feature_collection_includes_a_hex_dot_color():
    rows = [_row("BU1", "Centrum", 0.8, (5.4, 51.4))]
    fc = build_feature_collection(rows)
    props = fc["features"][0]["properties"]
    assert props["color_hex"].startswith("#")
    assert len(props["color_hex"]) == 7


def test_scale_bar_widths_scales_to_shown_rows_not_full_range():
    # All three scores are clustered near the top of [0, 1] -- against the
    # full range they'd all render as near-full bars; scaled to just these
    # rows, the spread should be visible (0%, 50%, 100%).
    rows = [
        {"category_score": 0.90},
        {"category_score": 0.95},
        {"category_score": 1.00},
    ]

    result = scale_bar_widths(rows)

    assert [r["bar_pct"] for r in result] == pytest.approx([0.0, 50.0, 100.0])


def test_scale_bar_widths_none_score_gets_none_bar_pct():
    rows = [{"category_score": 0.5}, {"category_score": None}]

    result = scale_bar_widths(rows)

    assert result[0]["bar_pct"] == 100.0  # sole real score -> top of its own range
    assert result[1]["bar_pct"] is None


def test_scale_bar_widths_all_none_stays_none():
    rows = [{"category_score": None}, {"category_score": None}]

    result = scale_bar_widths(rows)

    assert all(r["bar_pct"] is None for r in result)


def test_scale_bar_widths_tied_scores_get_full_bar_not_divide_by_zero():
    rows = [{"category_score": 0.7}, {"category_score": 0.7}]

    result = scale_bar_widths(rows)

    assert all(r["bar_pct"] == 100.0 for r in result)


def test_scale_bar_widths_preserves_other_fields():
    rows = [{"category_score": 0.5, "name": "Centrum"}]

    result = scale_bar_widths(rows)

    assert result[0]["name"] == "Centrum"
