"""Hardware-independent image processing and image encoding."""

import cv2
import numpy as np

SUBMISSION_BACKGROUND_SIGMA = 80.0
SUBMISSION_CLAHE_CLIP_LIMIT = 1.0


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
    illumination_strength=0.9,
    clahe_clip_limit=SUBMISSION_CLAHE_CLIP_LIMIT,
    background_sigma=SUBMISSION_BACKGROUND_SIGMA,
    gamma=1.0,
):
    """Correct broad illumination variation while retaining fine detail."""
    if frame is None or getattr(frame, "size", 0) == 0:
        raise ValueError("frame must be non-empty")
    if not 0 <= illumination_strength <= 1:
        raise ValueError("illumination_strength must be between 0 and 1")
    if clahe_clip_limit <= 0:
        raise ValueError("clahe_clip_limit must be positive")
    if gamma <= 0:
        raise ValueError("gamma must be positive")

    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if background_sigma <= 0:
        raise ValueError("background_sigma must be positive")

    background = cv2.GaussianBlur(gray, (0, 0), background_sigma)
    background = np.maximum(background, 1)
    # Anchor correction at the existing paper tone rather than 255. This
    # flattens broad shadows without aggressively whitening the whole page.
    target_tone = float(np.median(background))
    normalized = np.clip(gray.astype(np.float32) / background * target_tone, 0, 255).astype(
        np.uint8
    )
    corrected = cv2.addWeighted(
        gray,
        1.0 - illumination_strength,
        normalized,
        illumination_strength,
        0,
    )
    if gamma != 1.0:
        lookup = np.array([((value / 255.0) ** gamma) * 255 for value in range(256)])
        corrected = cv2.LUT(corrected, lookup.astype(np.uint8))

    clahe = cv2.createCLAHE(clipLimit=clahe_clip_limit, tileGridSize=(8, 8))
    clean = clahe.apply(corrected)

    if sharpen:
        blur = cv2.GaussianBlur(clean, (0, 0), 1.0)
        clean = cv2.addWeighted(clean, 1.15, blur, -0.15, 0)

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


def process_submission(frame, roi, max_dimension=1600, enhance=True):
    """Rotate/crop/clean a frame for compact handwritten-work submission."""
    cropped = crop_roi(frame, roi)
    if enhance:
        processed = cleanup_submission(cropped)
    elif len(cropped.shape) == 2:
        processed = cropped.copy()
    else:
        processed = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    return downscale_max_dimension(processed, max_dimension)


def encode_png(frame, compression=6):
    if not 0 <= compression <= 9:
        raise ValueError("PNG compression must be between 0 and 9")
    success, encoded = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, compression])
    if not success:
        raise ValueError("PNG encoding failed")
    return encoded.tobytes()
