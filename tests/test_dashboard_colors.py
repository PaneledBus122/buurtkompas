"""Unit tests for the pure score-to-color mapping (dashboard/colors.py).

Drop this module in ``tests/test_dashboard_colors.py``.
"""

from buurtkompas.dashboard.colors import (
    FILL_ALPHA,
    NO_DATA_COLOR,
    legend_gradient_css,
    score_to_color,
    score_to_hex,
)


def test_none_score_is_no_data_color():
    assert score_to_color(None) == NO_DATA_COLOR


def test_score_zero_is_blue_stop():
    assert score_to_color(0.0) == [0x24, 0x50, 0x8F, FILL_ALPHA]


def test_score_one_is_orange_stop():
    assert score_to_color(1.0) == [0xC8, 0x6A, 0x1D, FILL_ALPHA]


def test_score_half_is_neutral_gray_stop():
    assert score_to_color(0.5) == [0xC7, 0xC4, 0xB8, FILL_ALPHA]


def test_score_interpolates_between_stops():
    # 0.125 is halfway between the blue (0.0) and light-blue (0.25) stops.
    color = score_to_color(0.125)
    expected_r = round((0x24 + 0x9F) / 2)
    expected_g = round((0x50 + 0xB4) / 2)
    expected_b = round((0x8F + 0xD2) / 2)
    assert color == [expected_r, expected_g, expected_b, FILL_ALPHA]


def test_out_of_range_scores_are_clamped_not_erroring():
    # Shouldn't happen given percent_rank()'s [0, 1] range, but a defensive
    # clamp is cheaper than a crash if a future scoring change ever emits
    # something outside [0, 1].
    assert score_to_color(-0.5) == score_to_color(0.0)
    assert score_to_color(1.5) == score_to_color(1.0)


def test_score_to_hex_matches_score_to_color_without_alpha():
    r, g, b, _alpha = score_to_color(0.5)
    assert score_to_hex(0.5) == f"#{r:02x}{g:02x}{b:02x}"


def test_score_to_hex_none_matches_no_data_color():
    r, g, b, _alpha = NO_DATA_COLOR
    assert score_to_hex(None) == f"#{r:02x}{g:02x}{b:02x}"


def test_legend_gradient_css_is_a_linear_gradient_spanning_0_to_100_percent():
    gradient = legend_gradient_css()
    assert gradient.startswith("linear-gradient(to right,")
    assert "0%" in gradient
    assert "100%" in gradient
    # Endpoints must match the map's own worst/best colors, so the legend
    # can never visually disagree with the choropleth it's labeling.
    assert score_to_hex(0.0) in gradient
    assert score_to_hex(1.0) in gradient
