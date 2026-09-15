from unittest.mock import Mock, patch

import pytest

from buurtkompas.dashboard import commute


def _mock_response(json_data):
    response = Mock()
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def test_api_key_raises_clear_error_when_unset(monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ORS_API_KEY"):
        commute._api_key()


@patch("buurtkompas.dashboard.commute.requests.get")
def test_geocode_address_returns_lon_lat_of_best_match(mock_get, monkeypatch):
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    mock_get.return_value = _mock_response(
        {
            "features": [
                {"geometry": {"type": "Point", "coordinates": [5.4778, 51.4381]}},
                {"geometry": {"type": "Point", "coordinates": [5.5, 51.5]}},
            ]
        }
    )

    result = commute.geocode_address("Eindhoven Centraal Station")

    assert result == (5.4778, 51.4381)
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["api_key"] == "test-key"
    assert kwargs["params"]["text"] == "Eindhoven Centraal Station"


@patch("buurtkompas.dashboard.commute.requests.get")
def test_geocode_address_returns_none_when_no_features(mock_get, monkeypatch):
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    mock_get.return_value = _mock_response({"features": []})

    result = commute.geocode_address("asdkjaslkdjaslkdj nonsense")

    assert result is None


def test_geocode_address_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ORS_API_KEY"):
        commute.geocode_address("Eindhoven")


@patch("buurtkompas.dashboard.commute.requests.post")
def test_fetch_commute_minutes_converts_seconds_to_minutes(mock_post, monkeypatch):
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    mock_post.return_value = _mock_response({"durations": [[600.0], [1800.0]]})

    result = commute.fetch_commute_minutes(
        destination=(5.48, 51.44), origins=[(5.47, 51.43), (5.30, 51.20)]
    )

    assert result == [10.0, 30.0]
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "test-key"
    body = kwargs["json"]
    assert body["locations"] == [[5.47, 51.43], [5.30, 51.20], [5.48, 51.44]]
    assert body["sources"] == [0, 1]
    assert body["destinations"] == [2]
    assert body["metrics"] == ["duration"]


@patch("buurtkompas.dashboard.commute.requests.post")
def test_fetch_commute_minutes_preserves_null_for_unreachable_origin(
    mock_post, monkeypatch
):
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    mock_post.return_value = _mock_response({"durations": [[600.0], [None]]})

    result = commute.fetch_commute_minutes(
        destination=(5.48, 51.44), origins=[(5.47, 51.43), (5.30, 51.20)]
    )

    assert result == [10.0, None]


def test_fetch_commute_minutes_rejects_over_matrix_cap(monkeypatch):
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    with pytest.raises(ValueError, match="3500"):
        commute.fetch_commute_minutes(
            destination=(5.48, 51.44),
            origins=[(5.0, 51.0)] * (commute._MATRIX_MAX_CELLS + 1),
        )


def test_compute_commute_percentiles_shortest_gets_highest_score():
    scores = commute.compute_commute_percentiles(
        {"BU1": 10.0, "BU2": 20.0, "BU3": 30.0}
    )

    assert scores["BU1"] > scores["BU2"] > scores["BU3"]
    assert scores["BU3"] == 0.0
    assert scores["BU1"] == 1.0


def test_compute_commute_percentiles_ties_share_the_same_score():
    scores = commute.compute_commute_percentiles(
        {"BU1": 10.0, "BU2": 10.0, "BU3": 30.0}
    )

    assert scores["BU1"] == scores["BU2"]
    assert scores["BU1"] > scores["BU3"]


def test_compute_commute_percentiles_none_duration_stays_none():
    scores = commute.compute_commute_percentiles({"BU1": 10.0, "BU2": None})

    assert scores["BU2"] is None
    # Only one usable region to rank among (BU2 is excluded, same as a
    # region below fct_category_score's coverage threshold) — matches
    # Postgres percent_rank()'s own definition for a single-row window.
    assert scores["BU1"] == 0.0


def test_compute_commute_percentiles_all_none_returns_all_none():
    scores = commute.compute_commute_percentiles({"BU1": None, "BU2": None})

    assert scores == {"BU1": None, "BU2": None}


def test_compute_commute_percentiles_single_region_scores_zero():
    scores = commute.compute_commute_percentiles({"BU1": 15.0})

    assert scores == {"BU1": 0.0}
