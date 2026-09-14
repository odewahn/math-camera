"""Hardware-independent image processing and JPEG encoding."""

import cv2


def rotate_frame(frame, rotation):
    rotation %= 4
    if rotation == 0:
        return frame.copy()
    codes = {1: cv2.ROTATE_90_CLOCKWISE, 2: cv2.ROTATE_180, 3: cv2.ROTATE_90_COUNTERCLOCKWISE}
    return cv2.rotate(frame, codes[rotation])


def resize_frame(frame, dimensions):
    width, height = dimensions
    if width <= 0 or height <= 0:
        raise ValueError("dimensions must be positive")
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def validate_roi(roi):
    if roi is None:
        return None
    if len(roi) != 4 or any(not 0 <= value <= 1 for value in roi):
        raise ValueError("ROI values must be normalized to 0..1")
    x, y, width, height = roi
    if width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise ValueError("ROI must be non-empty and inside the frame")
    return tuple(float(value) for value in roi)


def crop_roi(frame, roi):
    roi = validate_roi(roi)
    if roi is None:
        return frame.copy()
    x, y, width, height = roi
    frame_height, frame_width = frame.shape[:2]
    left, top = round(x * frame_width), round(y * frame_height)
    right = round((x + width) * frame_width)
    bottom = round((y + height) * frame_height)
    if right <= left or bottom <= top:
        raise ValueError("ROI is smaller than one pixel")
    return frame[top:bottom, left:right].copy()


def encode_jpeg(frame, quality=95):
    if not 0 < quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100")
    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        raise ValueError("JPEG encoding failed")
    return encoded.tobytes()
