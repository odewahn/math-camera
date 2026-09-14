"""Serialized capture pipeline and macOS clipboard adapter boundary."""

import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass

from .processing import crop_roi, encode_jpeg, rotate_frame
from .state import CaptureStatus, SharedState


@dataclass(frozen=True)
class CaptureRequest:
    frame: object
    settings: object
    quality: int
    label: str


class MacOSClipboard:
    def copy_jpeg(self, payload: bytes):
        fd, path = tempfile.mkstemp(prefix="math-camera-", suffix=".jpg", dir="/tmp")
        os.close(fd)
        try:
            with open(path, "wb") as image_file:
                image_file.write(payload)
            script = f'set the clipboard to (read POSIX file "{path}" as JPEG picture)'
            subprocess.run(["/usr/bin/osascript", "-e", script], check=True)
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


class CaptureWorker:
    def __init__(self, state: SharedState, clipboard, sound=None):
        self.state, self.clipboard, self.sound = state, clipboard, sound
        self._condition = threading.Condition()
        self._pending = None
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="capture-worker", daemon=True)
        self._thread.start()

    def submit(self, request):
        with self._condition:
            if self._stopping:
                return False
            self._pending = request
            self._condition.notify()
            return True

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait()
                if self._pending is None and self._stopping:
                    return
                request, self._pending = self._pending, None
            self.state.publish_status(CaptureStatus.CAPTURING, "Capturing")
            try:
                frame = rotate_frame(request.frame, request.settings.rotation)
                if request.settings.mode == "submission":
                    frame = crop_roi(frame, request.settings.roi)
                try:
                    payload = encode_jpeg(frame, request.quality)
                except Exception as error:
                    raise RuntimeError(f"encoding failed: {error}") from error
                try:
                    self.clipboard.copy_jpeg(payload)
                except Exception as error:
                    raise RuntimeError(f"clipboard failed: {error}") from error
                self.state.publish_status(
                    CaptureStatus.COPIED,
                    f"Copied {request.label} frame",
                    len(payload),
                )
                if self.sound:
                    self.sound(True)
            except Exception as error:
                self.state.publish_status(CaptureStatus.ERROR, f"capture/clipboard failed: {error}")
                if self.sound:
                    try:
                        self.sound(False)
                    except Exception:
                        pass

    def close(self, timeout=5):
        with self._condition:
            self._stopping = True
            self._pending = None
            self._condition.notify()
        self._thread.join(timeout)

    @property
    def alive(self):
        return self._thread.is_alive()
