import numpy as np
import pytest

from math_camera.processing import crop_roi, encode_jpeg, rotate_frame, validate_roi


def test_rotation_dimensions_and_orientation():
    frame = np.arange(2 * 3, dtype=np.uint8).reshape(2, 3)
    assert rotate_frame(frame, 0).shape == (2, 3)
    assert rotate_frame(frame, 1).shape == (3, 2)
    assert rotate_frame(frame, 2).shape == (2, 3)
    assert rotate_frame(frame, 3).shape == (3, 2)
    assert rotate_frame(frame, 1)[0, 0] == frame[1, 0]


def test_rotation_is_copy():
    frame = np.zeros((2, 2), dtype=np.uint8)
    rotated = rotate_frame(frame, 0)
    rotated[0, 0] = 1
    assert frame[0, 0] == 0


@pytest.mark.parametrize("roi", [(-0.1, 0, 1, 1), (0, 0, 0, 1), (0, 0, 1.1, 1), (0, 0, 1, 1.1)])
def test_invalid_roi(roi):
    with pytest.raises(ValueError):
        validate_roi(roi)


def test_crop_roi_and_jpeg():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    cropped = crop_roi(frame, (0.25, 0.1, 0.5, 0.5))
    assert cropped.shape[:2] == (50, 100)
    assert encode_jpeg(frame, 55)[:2] == b"\xff\xd8"
