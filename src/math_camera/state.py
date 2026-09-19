"""Thread-safe application state shared by capture, preview, and UI code."""

import threading
import time
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class CameraInfo:
    unique_id: str
    name: str
    index: int


@dataclass
class CaptureSettings:
    camera_id: str | None = None
    rotation: int = 1
    roi: tuple[float, float, float, float] | None = (0.0, 0.0, 1.0, 1.0)
    enhance: bool = True

    def __post_init__(self):
        self.rotation %= 4


class CaptureStatus(Enum):
    READY = "ready"
    CAPTURING = "capturing"
    COPIED = "copied"
    ERROR = "error"


@dataclass(frozen=True)
class CaptureStatusInfo:
    state: CaptureStatus
    message: str
    byte_size: int | None = None
    timestamp: float | None = None


class SharedState:
    def __init__(self, settings: CaptureSettings | None = None):
        self._lock = threading.RLock()
        self._settings = settings or CaptureSettings()
        self._status = CaptureStatusInfo(CaptureStatus.READY, "Ready")

    def get_settings(self) -> CaptureSettings:
        with self._lock:
            return CaptureSettings(**self._settings.__dict__)

    def update_settings(self, **changes) -> CaptureSettings:
        with self._lock:
            values = self._settings.__dict__.copy()
            values.update(changes)
            self._settings = CaptureSettings(**values)
            return self.get_settings()

    def get_status(self) -> CaptureStatusInfo:
        with self._lock:
            return self._status

    def publish_status(self, state, message, byte_size=None):
        with self._lock:
            self._status = CaptureStatusInfo(state, message, byte_size, time.time())
            return self._status


class FrameStore:
    """Owns raw BGR frames and always returns isolated snapshots."""

    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None
        self._generation = 0

    def set(self, frame):
        with self._lock:
            self._frame = frame.copy()
            self._generation += 1

    def snapshot(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def clear(self):
        with self._lock:
            self._frame = None
            self._generation += 1

    @property
    def generation(self):
        with self._lock:
            return self._generation
