import pytest

from math_camera.gui import CameraGui


def test_roi_handle_hit_testing_prefers_nearest_handle():
    handles = {
        "tl": (100, 100),
        "top": (150, 100),
        "tr": (200, 100),
    }

    assert CameraGui._hit_test_roi_handle(102, 102, handles) == "tl"
    assert CameraGui._hit_test_roi_handle(148, 101, handles) == "top"


def test_roi_handle_hit_testing_does_not_claim_distant_pointer():
    handles = {"tl": (100, 100)}

    assert CameraGui._hit_test_roi_handle(140, 140, handles) is None


def test_shift_resize_projects_pointer_onto_opposite_handle_line():
    roi = (0.2, 0.2, 0.4, 0.4)
    display_rect = (0, 0, 1000, 1000)

    unchanged = CameraGui._shift_resize_roi(
        "tl",
        200,
        200,
        200,
        200,
        roi,
        display_rect,
    )
    resized = CameraGui._shift_resize_roi(
        "tl",
        300,
        300,
        200,
        200,
        roi,
        display_rect,
    )

    assert unchanged == pytest.approx(roi)
    # Moving along the diagonal keeps the top-left handle fixed.
    assert resized[0:2] == roi[0:2]
    assert resized[2] == pytest.approx(0.5)
    assert resized[3] == pytest.approx(0.5)


def test_shift_resize_moves_the_opposite_handle():
    assert CameraGui._opposite_handle("tl") == "br"
    assert CameraGui._opposite_handle("right") == "left"
