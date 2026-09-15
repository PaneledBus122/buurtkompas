"""Unit tests for the pure geometry/feature-collection transforms in
dashboard/data.py (fetch_* functions need a live DB and aren't covered here —
this targets the parts that don't).

Drop this module in ``tests/test_dashboard_data.py``.
"""

from buurtkompas.dashboard.data import (
    build_feature_collection,
    compute_view_state,
    merge_region_scores,
)


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
