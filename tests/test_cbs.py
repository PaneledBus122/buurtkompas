from unittest.mock import Mock, patch

from buurtkompas.extract import cbs


def _mock_response(json_data):
    response = Mock()
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


@patch("buurtkompas.extract.cbs.requests.get")
def test_fetch_buurt_codes_filters_by_bu_prefix(mock_get):
    mock_get.return_value = _mock_response(
        {
            "value": [
                {"Identifier": "WK077201", "Title": "Some wijk"},
                {"Identifier": "BU07720101", "Title": "Some buurt"},
                {"Identifier": "BU07720102", "Title": "Another buurt"},
            ]
        }
    )

    result = cbs.fetch_buurt_codes(["GM0772"])

    assert result == ["BU07720101", "BU07720102"]


@patch("buurtkompas.extract.cbs.requests.get")
def test_fetch_buurt_codes_queries_each_gemeente_separately(mock_get):
    mock_get.side_effect = [
        _mock_response({"value": [{"Identifier": "BU07720101"}]}),
        _mock_response(
            {"value": [{"Identifier": "WK086101"}, {"Identifier": "BU08610101"}]}
        ),
    ]

    result = cbs.fetch_buurt_codes(["GM0772", "GM0861"])

    assert result == ["BU07720101", "BU08610101"]
    filters = [call.kwargs["params"]["$filter"] for call in mock_get.call_args_list]
    assert filters == [
        "DimensionGroupId eq 'GM0772'",
        "DimensionGroupId eq 'GM0861'",
    ]


@patch("buurtkompas.extract.cbs.requests.get")
def test_fetch_observations_follows_pagination(mock_get):
    first_page = _mock_response(
        {
            "value": [{"WijkenEnBuurten": "BU07720101", "Value": 1.1}],
            "@odata.nextLink": "https://datasets.cbs.nl/odata/v1/CBS/85984NED/Observations?page=2",
        }
    )
    second_page = _mock_response(
        {"value": [{"WijkenEnBuurten": "BU07720102", "Value": 2.2}]}
    )
    mock_get.side_effect = [first_page, second_page]

    result = cbs.fetch_observations("D000045", ["BU07720101", "BU07720102"])

    assert result == [
        {"region_id": "BU07720101", "value": 1.1},
        {"region_id": "BU07720102", "value": 2.2},
    ]
    assert mock_get.call_count == 2


@patch("buurtkompas.extract.cbs.fetch_observations")
@patch("buurtkompas.extract.cbs.fetch_buurt_codes")
def test_extract_all_builds_long_format_dataframe(mock_fetch_codes, mock_fetch_obs):
    mock_fetch_codes.return_value = ["BU07720101"]
    mock_fetch_obs.return_value = [{"region_id": "BU07720101", "value": 1.1}]

    df = cbs.extract_all()

    assert list(df.columns) == [
        "region_id",
        "indicator_id",
        "indicator_label",
        "category",
        "value",
    ]
    assert len(df) == len(cbs.MEASURES)


@patch("buurtkompas.extract.cbs.fetch_observations")
def test_fetch_population_maps_region_to_value(mock_fetch_obs):
    mock_fetch_obs.return_value = [
        {"region_id": "BU07720101", "value": 5000},
        {"region_id": "BU07720102", "value": 3200},
    ]

    result = cbs.fetch_population(["BU07720101", "BU07720102"])

    assert result == {"BU07720101": 5000, "BU07720102": 3200}
    mock_fetch_obs.assert_called_once_with(
        cbs.POPULATION_MEASURE_CODE, ["BU07720101", "BU07720102"]
    )


@patch("buurtkompas.extract.cbs.fetch_population")
@patch("buurtkompas.extract.cbs.fetch_buurt_codes")
def test_extract_population_builds_region_population_dataframe(
    mock_fetch_codes, mock_fetch_population
):
    mock_fetch_codes.return_value = ["BU07720101"]
    mock_fetch_population.return_value = {"BU07720101": 5000}

    df = cbs.extract_population()

    assert list(df.columns) == ["region_id", "population"]
    assert df.to_dict("records") == [{"region_id": "BU07720101", "population": 5000}]
