import threading
import time

import cv2
import dispatch
import numpy as np
import objc

from AVFoundation import (
    AVCaptureDevice,
    AVCaptureDeviceInput,
    AVCaptureSession,
    AVCaptureVideoDataOutput,
    AVCaptureSessionPresetHigh,
    AVMediaTypeVideo,
)
from CoreMedia import CMSampleBufferGetImageBuffer
from Quartz import (
    CVPixelBufferGetBaseAddress,
    CVPixelBufferGetBytesPerRow,
    CVPixelBufferGetHeight,
    CVPixelBufferGetWidth,
    CVPixelBufferLockBaseAddress,
    CVPixelBufferUnlockBaseAddress,
    kCVPixelBufferPixelFormatTypeKey,
    kCVPixelFormatType_32BGRA,
)
from Foundation import NSObject


class NativeCameraDelegate(NSObject):
    def initWithCamera_(self, camera):
        self = objc.super(NativeCameraDelegate, self).init()

        if self is None:
            return None

        self.camera = camera
        return self

    def captureOutput_didOutputSampleBuffer_fromConnection_(
        self,
        _output,
        sample_buffer,
        _connection,
    ):
        try:
            frame = self.camera.frame_from_sample_buffer(sample_buffer)

            if frame is not None:
                self.camera.set_latest_frame(frame)
        except Exception as error:
            self.camera.report_callback_error(error)


class NativeCameraCapture:
    def __init__(self, camera_index, width, height):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.frame_lock = threading.Lock()
        self.lifecycle_lock = threading.Lock()
        self.latest_frame = None
        self.session = None
        self.output = None
        self.delegate = None
        self.callback_queue = None
        self.shutdown_event = threading.Event()
        self.sleeping_event = threading.Event()
        self.frame_ready_event = threading.Event()
        self.operation_lock = threading.Lock()
        self.start_thread = None
        self.restart_thread = None
        self.resume_thread = None

    @staticmethod
    def device_count():
        return len(
            AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo)
        )

    def get_frame(self):
        with self.frame_lock:
            if self.latest_frame is None:
                return None

            return self.latest_frame.copy()

    def set_latest_frame(self, frame):
        with self.frame_lock:
            self.latest_frame = frame
            self.frame_ready_event.set()

    def clear_latest_frame(self):
        with self.frame_lock:
            self.latest_frame = None
            self.frame_ready_event.clear()

    def frame_from_sample_buffer(self, sample_buffer):
        pixel_buffer = CMSampleBufferGetImageBuffer(sample_buffer)

        if pixel_buffer is None:
            return None

        status = CVPixelBufferLockBaseAddress(pixel_buffer, 0)

        if status != 0:
            return None

        try:
            width = CVPixelBufferGetWidth(pixel_buffer)
            height = CVPixelBufferGetHeight(pixel_buffer)
            bytes_per_row = CVPixelBufferGetBytesPerRow(pixel_buffer)
            base_address = CVPixelBufferGetBaseAddress(pixel_buffer)

            if not base_address:
                return None

            buffer_size = bytes_per_row * height
            bgra = np.frombuffer(
                base_address.as_buffer(buffer_size),
                dtype=np.uint8,
                count=buffer_size,
            ).reshape(height, bytes_per_row // 4, 4)
            bgra = bgra[:, :width, :].copy()

            return cv2.cvtColor(
                bgra,
                cv2.COLOR_BGRA2BGR,
            )
        finally:
            CVPixelBufferUnlockBaseAddress(pixel_buffer, 0)

    def report_callback_error(self, error):
        print(f"Native camera frame error: {error}")

    def start_async(self):
        if (
            self.shutdown_event.is_set()
            or self.sleeping_event.is_set()
        ):
            return

        if (
            self.start_thread is not None
            and self.start_thread.is_alive()
        ):
            return

        self.start_thread = threading.Thread(
            target=self.start_until_ready,
            name="native-camera-start",
            daemon=True,
        )
        self.start_thread.start()

    def start_until_ready(self):
        with self.operation_lock:
            while not (
                self.shutdown_event.is_set()
                or self.sleeping_event.is_set()
            ):
                try:
                    self.start_session()
                    print(
                        f"Native camera started "
                        f"(AVFoundation device {self.camera_index})"
                    )
                    return
                except Exception as error:
                    print(f"Waiting for native camera: {error}")
                    self.shutdown_event.wait(1.0)

    def start_session(self):
        devices = list(
            AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo)
        )

        if not devices:
            raise RuntimeError("No AVFoundation cameras are available")

        if self.camera_index >= len(devices):
            self.camera_index = 0

        device = devices[self.camera_index]
        capture_input, error = (
            AVCaptureDeviceInput.deviceInputWithDevice_error_(
                device,
                None,
            )
        )

        if capture_input is None:
            raise RuntimeError(str(error))

        session = AVCaptureSession.alloc().init()
        session.setSessionPreset_(AVCaptureSessionPresetHigh)

        if not session.canAddInput_(capture_input):
            raise RuntimeError("AVFoundation rejected the camera input")

        session.addInput_(capture_input)

        output = AVCaptureVideoDataOutput.alloc().init()
        output.setAlwaysDiscardsLateVideoFrames_(True)
        output.setVideoSettings_({
            kCVPixelBufferPixelFormatTypeKey:
                kCVPixelFormatType_32BGRA,
        })

        delegate = NativeCameraDelegate.alloc().initWithCamera_(self)
        callback_queue = dispatch.dispatch_queue_create(
            b"math-camera.native-camera",
            None,
        )
        output.setSampleBufferDelegate_queue_(
            delegate,
            callback_queue,
        )

        if not session.canAddOutput_(output):
            raise RuntimeError("AVFoundation rejected the video output")

        session.addOutput_(output)
        session.startRunning()

        with self.lifecycle_lock:
            self.session = session
            self.output = output
            self.delegate = delegate
            self.callback_queue = callback_queue

    def stop(self):
        with self.lifecycle_lock:
            session = self.session
            output = self.output
            self.session = None
            self.output = None
            self.delegate = None
            self.callback_queue = None

        if output is not None:
            output.setSampleBufferDelegate_queue_(None, None)

        if session is not None:
            session.stopRunning()

        self.clear_latest_frame()

    def restart_async(self):
        if (
            self.shutdown_event.is_set()
            or self.sleeping_event.is_set()
        ):
            return

        if (
            self.restart_thread is not None
            and self.restart_thread.is_alive()
        ):
            return

        self.restart_thread = threading.Thread(
            target=self.restart_until_ready,
            name="native-camera-restart",
            daemon=True,
        )
        self.restart_thread.start()

    def restart_until_ready(self):
        with self.operation_lock:
            self.stop()
            self._start_until_ready()

    def _start_until_ready(self):
        while not (
            self.shutdown_event.is_set()
            or self.sleeping_event.is_set()
        ):
            try:
                self.start_session()
                print(
                    f"Native camera started "
                    f"(AVFoundation device {self.camera_index})"
                )
                return
            except Exception as error:
                print(f"Waiting for native camera: {error}")
                self.shutdown_event.wait(1.0)

    def pause_for_sleep(self):
        self.sleeping_event.set()
        self.clear_latest_frame()
        print(
            "Native camera entering sleep; preserving AVFoundation "
            "session for wake."
        )

    def resume_async(self):
        if self.shutdown_event.is_set():
            return

        self.sleeping_event.clear()

        if (
            self.resume_thread is not None
            and self.resume_thread.is_alive()
        ):
            return

        self.resume_thread = threading.Thread(
            target=self.resume_until_ready,
            name="native-camera-resume",
            daemon=True,
        )
        self.resume_thread.start()

    def resume_until_ready(self):
        with self.operation_lock:
            with self.lifecycle_lock:
                session = self.session

            if session is not None:
                started_at = time.monotonic()
                print("Resuming existing native camera session...")

                try:
                    session.startRunning()

                    if self.frame_ready_event.wait(timeout=3.0):
                        elapsed = time.monotonic() - started_at
                        print(
                            "Native camera resumed "
                            f"in {elapsed:.1f}s "
                            f"(AVFoundation device {self.camera_index})"
                        )
                        return

                    print(
                        "Existing native camera session did not deliver "
                        "a frame; rebuilding it."
                    )
                except Exception as error:
                    print(
                        f"Existing native camera session failed: {error}; "
                        "rebuilding it."
                    )

                self.stop()

            self._start_until_ready()

    def set_camera_index(self, camera_index):
        self.camera_index = camera_index
        self.restart_async()

    def close(self):
        self.shutdown_event.set()
        self.stop()
