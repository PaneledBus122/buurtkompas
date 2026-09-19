from unittest.mock import Mock, patch

import pytest
import requests

from buurtkompas.extract import politie


def _mock_response(json_data, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    if status_code < 400:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=response
        )
    return response


@patch("buurtkompas.extract.politie.requests.get")
def test_fetch_crime_counts_filters_to_wanted_regions(mock_get):
    mock_get.return_value = _mock_response(
        {
            "value": [
                {"WijkenEnBuurten": "BU07720101", "GeregistreerdeMisdrijven_1": 42},
                {"WijkenEnBuurten": "BU99999999", "GeregistreerdeMisdrijven_1": 999},
            ]
        }
    )

    result = politie.fetch_crime_counts("0.0.0 ", ["BU07720101"])

    assert result == [{"region_id": "BU07720101", "value": 42}]


@patch("buurtkompas.extract.politie.requests.get")
def test_fetch_crime_counts_requests_json_format(mock_get):
    """OData v3 (dataderden.cbs.nl) defaults to Atom/XML, unlike the v4
    endpoint cbs.py uses — without "$format": "json" in the request,
    response.json() raises JSONDecodeError against the real API even
    though a Mock response happily returns whatever .json() is told to.
    """
    mock_get.return_value = _mock_response({"value": []})

    politie.fetch_crime_counts("0.0.0 ", ["BU07720101"])

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["$format"] == "json"


@patch("buurtkompas.extract.politie.requests.get")
def test_fetch_crime_counts_follows_odata_v3_next_link(mock_get):
    first_page = _mock_response(
        {
            "value": [
                {"WijkenEnBuurten": "BU07720101", "GeregistreerdeMisdrijven_1": 42}
            ],
            "odata.nextLink": (
                "https://dataderden.cbs.nl/ODataFeed/odata/47018NED/TypedDataSet?$skip=1000"
            ),
        }
    )
    second_page = _mock_response(
        {"value": [{"WijkenEnBuurten": "BU07720102", "GeregistreerdeMisdrijven_1": 7}]}
    )
    mock_get.side_effect = [first_page, second_page]

    result = politie.fetch_crime_counts("0.0.0 ", ["BU07720101", "BU07720102"])

    assert result == [
        {"region_id": "BU07720101", "value": 42},
        {"region_id": "BU07720102", "value": 7},
    ]
    assert mock_get.call_count == 2


@patch("buurtkompas.extract.politie.sleep")
@patch("buurtkompas.extract.politie.requests.get")
def test_get_with_retry_retries_on_server_error(mock_get, mock_sleep):
    mock_get.side_effect = [
        _mock_response({}, status_code=503),
        _mock_response({"value": []}),
    ]

    response = politie._get_with_retry("https://example.test")

    assert response.status_code == 200
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()


@patch("buurtkompas.extract.politie.sleep")
@patch("buurtkompas.extract.politie.requests.get")
def test_get_with_retry_retries_on_connection_error(mock_get, mock_sleep):
    mock_get.side_effect = [
        requests.exceptions.ConnectionError("boom"),
        _mock_response({"value": []}),
    ]

    response = politie._get_with_retry("https://example.test")

    assert response.status_code == 200
    assert mock_get.call_count == 2


@patch("buurtkompas.extract.politie.sleep")
@patch("buurtkompas.extract.politie.requests.get")
def test_get_with_retry_does_not_retry_client_error(mock_get, mock_sleep):
    mock_get.return_value = _mock_response({}, status_code=404)

    with pytest.raises(requests.exceptions.HTTPError):
        politie._get_with_retry("https://example.test")

    assert mock_get.call_count == 1
    mock_sleep.assert_not_called()


@patch("buurtkompas.extract.politie.sleep")
@patch("buurtkompas.extract.politie.requests.get")
def test_get_with_retry_raises_after_exhausting_retries(mock_get, mock_sleep):
    mock_get.return_value = _mock_response({}, status_code=503)

    with pytest.raises(requests.exceptions.HTTPError):
        politie._get_with_retry("https://example.test")

    assert mock_get.call_count == politie.MAX_RETRIES


@patch("buurtkompas.extract.politie.fetch_crime_counts")
@patch("buurtkompas.extract.politie.fetch_buurt_codes")
def test_extract_all_builds_long_format_dataframe(mock_fetch_codes, mock_fetch_counts):
    mock_fetch_codes.return_value = ["BU07720101"]
    mock_fetch_counts.return_value = [{"region_id": "BU07720101", "value": 42}]

    df = politie.extract_all()

    assert list(df.columns) == [
        "region_id",
        "indicator_id",
        "indicator_label",
        "category",
        "value",
    ]
    assert len(df) == len(politie.MEASURES)
    row = df.iloc[0]
    assert row["indicator_id"] == "0.0.0"
    assert row["category"] == "safety"
    assert row["value"] == 42


@patch("buurtkompas.extract.politie.fetch_crime_counts")
@patch("buurtkompas.extract.politie.fetch_buurt_codes")
def test_extract_all_uses_configured_gemeente_codes(
    mock_fetch_codes, mock_fetch_counts
):
    mock_fetch_codes.return_value = []
    mock_fetch_counts.return_value = []

    politie.extract_all()

    mock_fetch_codes.assert_called_once_with(politie.GEMEENTE_CODES)
