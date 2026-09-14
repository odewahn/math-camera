"""Hardware-independent image processing and image encoding."""

import cv2
import numpy as np


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


def validate_roi(roi, allow_outside=0):
    if roi is None:
        return None
    if len(roi) != 4 or any(not -allow_outside <= value <= 1 + 2 * allow_outside for value in roi):
        raise ValueError("ROI values must be normalized to 0..1")
    x, y, width, height = roi
    if width <= 0 or height <= 0 or x + width > 1 + allow_outside or y + height > 1 + allow_outside:
        raise ValueError("ROI must be non-empty and inside the frame")
    return tuple(float(value) for value in roi)


def crop_roi(frame, roi):
    roi = validate_roi(roi, allow_outside=0.05)
    if roi is None:
        return frame.copy()
    x, y, width, height = roi
    frame_height, frame_width = frame.shape[:2]
    left = max(0, round(x * frame_width))
    top = max(0, round(y * frame_height))
    right = min(frame_width, round((x + width) * frame_width))
    bottom = min(frame_height, round((y + height) * frame_height))
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


def cleanup_submission(
    frame,
    sharpen=False,
    illumination_strength=0.85,
    clahe_clip_limit=1.2,
    background_sigma=None,
):
    """Correct broad illumination variation while retaining fine detail."""
    if frame is None or getattr(frame, "size", 0) == 0:
        raise ValueError("frame must be non-empty")
    if not 0 <= illumination_strength <= 1:
        raise ValueError("illumination_strength must be between 0 and 1")
    if clahe_clip_limit <= 0:
        raise ValueError("clahe_clip_limit must be positive")

    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if background_sigma is None:
        # Keep the estimate broader than ordinary handwriting, including for
        # small, tightly cropped ROIs. A broader estimate targets only the
        # largest-scale lighting gradients and leaves handwriting contrast in
        # the source image.
        background_sigma = max(40.0, min(gray.shape[:2]) / 6)
    if background_sigma <= 0:
        raise ValueError("background_sigma must be positive")

    background = cv2.GaussianBlur(gray, (0, 0), background_sigma)
    background = np.maximum(background, 1)
    target = float(np.median(background))
    normalized = np.clip(gray.astype(np.float32) / background * target, 0, 255).astype(np.uint8)
    # Blending avoids the bright/dark halos that full-strength division can
    # produce around strokes and other fine foreground detail.
    corrected = cv2.addWeighted(
        gray,
        1.0 - illumination_strength,
        normalized,
        illumination_strength,
        0,
    )
    clahe = cv2.createCLAHE(clipLimit=clahe_clip_limit, tileGridSize=(8, 8))
    clean = clahe.apply(corrected)

    if sharpen:
        blur = cv2.GaussianBlur(clean, (0, 0), 1.0)
        clean = cv2.addWeighted(clean, 1.1, blur, -0.1, 0)

    return clean


def downscale_max_dimension(image, max_dimension=1600):
    """Downscale an image only when its long edge exceeds ``max_dimension``."""
    if max_dimension <= 0:
        raise ValueError("max_dimension must be positive")
    height, width = image.shape[:2]
    scale = min(1.0, max_dimension / max(width, height))
    if scale == 1.0:
        return image.copy()
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def process_submission(frame, roi, max_dimension=1600):
    """Rotate/crop/clean a frame for compact handwritten-work submission."""
    cropped = crop_roi(frame, roi)
    return downscale_max_dimension(cleanup_submission(cropped), max_dimension)


def encode_png(frame, compression=6):
    if not 0 <= compression <= 9:
        raise ValueError("PNG compression must be between 0 and 9")
    success, encoded = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, compression])
    if not success:
        raise ValueError("PNG encoding failed")
    return encoded.tobytes()


def suggest_roi(frame, margin=0.03):
    """Suggest a normalized ROI around meaningful dark content, or return None."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    if not 0 <= margin < 0.5:
        raise ValueError("margin must be between 0 and 0.5")

    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    background = cv2.GaussianBlur(gray, (0, 0), 25)
    normalized = cv2.divide(gray, background, scale=255)
    mask = cv2.threshold(normalized, 245, 255, cv2.THRESH_BINARY_INV)[1]
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

    points = cv2.findNonZero(mask)
    if points is None:
        return None
    x, y, width, height = cv2.boundingRect(points)
    frame_height, frame_width = gray.shape[:2]
    if width < max(4, frame_width * 0.01) or height < max(4, frame_height * 0.01):
        return None

    pad_x, pad_y = round(width * margin), round(height * margin)
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(frame_width, x + width + pad_x)
    bottom = min(frame_height, y + height + pad_y)
    return (
        left / frame_width,
        top / frame_height,
        (right - left) / frame_width,
        (bottom - top) / frame_height,
    )
