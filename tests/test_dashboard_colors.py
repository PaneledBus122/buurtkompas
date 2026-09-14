"""Unit tests for the pure score-to-color mapping (dashboard/colors.py).

Drop this module in ``tests/test_dashboard_colors.py``.
"""

from buurtkompas.dashboard.colors import FILL_ALPHA, NO_DATA_COLOR, score_to_color


def test_none_score_is_no_data_color():
    assert score_to_color(None) == NO_DATA_COLOR


def test_score_zero_is_red_stop():
    assert score_to_color(0.0) == [215, 48, 39, FILL_ALPHA]


def test_score_one_is_green_stop():
    assert score_to_color(1.0) == [26, 152, 80, FILL_ALPHA]


def test_score_half_is_yellow_stop():
    assert score_to_color(0.5) == [255, 255, 191, FILL_ALPHA]


def test_score_interpolates_between_stops():
    # 0.25 is halfway between the red (0.0) and yellow (0.5) stops.
    color = score_to_color(0.25)
    expected_r = round((215 + 255) / 2)
    expected_g = round((48 + 255) / 2)
    expected_b = round((39 + 191) / 2)
    assert color == [expected_r, expected_g, expected_b, FILL_ALPHA]


def test_out_of_range_scores_are_clamped_not_erroring():
    # Shouldn't happen given percent_rank()'s [0, 1] range, but a defensive
    # clamp is cheaper than a crash if a future scoring change ever emits
    # something outside [0, 1].
    assert score_to_color(-0.5) == score_to_color(0.0)
    assert score_to_color(1.5) == score_to_color(1.0)
