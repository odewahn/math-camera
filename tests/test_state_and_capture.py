import threading

import numpy as np

from math_camera.cameras import next_camera, select_camera
from math_camera.capture import CaptureRequest, CaptureWorker
from math_camera.state import (
    CameraInfo,
    CaptureSettings,
    CaptureStatus,
    FrameStore,
    SharedState,
)


def test_frame_store_snapshots_are_isolated():
    store = FrameStore()
    frame = np.zeros((2, 2), dtype=np.uint8)
    store.set(frame)
    snapshot = store.snapshot()
    snapshot[0, 0] = 9
    assert store.snapshot()[0, 0] == 0


def test_camera_fallback_and_wrapping():
    cameras = [CameraInfo("a", "A", 0), CameraInfo("b", "B", 1)]
    assert select_camera(cameras, "missing").unique_id == "a"
    assert next_camera(cameras, "b").unique_id == "a"
    assert next_camera(cameras, "a", -1).unique_id == "b"


class Clipboard:
    def __init__(self):
        self.payloads = []
        self.event = threading.Event()

    def copy_jpeg(self, payload):
        self.payloads.append(payload)
        self.event.set()

    copy_png = copy_jpeg


class PngClipboard(Clipboard):
    def copy_png(self, payload):
        self.payloads.append(payload)
        self.event.set()


def test_worker_captures_and_shutdown_rejects_new_work():
    state, clipboard = SharedState(), Clipboard()
    worker = CaptureWorker(state, clipboard)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    request = CaptureRequest(frame, CaptureSettings(rotation=0), 80, "test")
    assert worker.submit(request)
    assert clipboard.event.wait(2)
    assert state.get_status().state == CaptureStatus.COPIED
    worker.close()
    assert not worker.submit(request)
    assert not worker.alive


def test_worker_submission_capture_uses_png_and_processing():
    state, clipboard = SharedState(), PngClipboard()
    worker = CaptureWorker(state, clipboard)
    frame = np.full((100, 200, 3), 230, dtype=np.uint8)
    frame[35:65, 70:130] = 20
    request = CaptureRequest(
        frame,
        CaptureSettings(rotation=0, roi=(0.2, 0.2, 0.6, 0.6)),
        80,
        "test",
    )
    assert worker.submit(request)
    assert clipboard.event.wait(2)
    assert clipboard.payloads[0][:8] == b"\x89PNG\r\n\x1a\n"
    worker.close()
