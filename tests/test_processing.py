import numpy as np
import pytest

from math_camera.processing import (
    crop_roi,
    encode_jpeg,
    encode_png,
    process_submission,
    rotate_frame,
    validate_roi,
)


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


def test_crop_roi_clamps_small_interactive_overshoot():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    cropped = crop_roi(frame, (-0.05, -0.05, 1.1, 1.1))
    assert cropped.shape[:2] == frame.shape[:2]


def test_submission_processing_is_grayscale_and_downscaled():
    frame = np.full((200, 400, 3), 235, dtype=np.uint8)
    frame[80:120, 100:300] = 30
    result = process_submission(frame, (0.1, 0.2, 0.8, 0.6), max_dimension=160)
    assert result.ndim == 2
    assert max(result.shape) == 160
    assert encode_png(result)[:8] == b"\x89PNG\r\n\x1a\n"


def test_submission_processing_can_disable_enhancement():
    frame = np.full((100, 200, 3), 180, dtype=np.uint8)
    frame[40:60, 80:120] = 90
    result = process_submission(frame, (0, 0, 1, 1), enhance=False)
    assert result.ndim == 2
    assert result[10, 10] == 180
    assert result[50, 100] == 90
