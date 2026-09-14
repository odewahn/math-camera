"""Small Dear PyGui preview and configuration panel."""

from __future__ import annotations

import cv2
import numpy as np

from .processing import resize_frame, rotate_frame
from .state import FrameStore, SharedState

PREVIEW_WIDTH = 960
PREVIEW_HEIGHT = 540


class CameraGui:
    """Dear PyGui consumer/controller for the shared camera application state."""

    def __init__(
        self, state, frame_store: FrameStore, camera, cameras, on_camera, on_capture, on_close
    ):
        self.state: SharedState = state
        self.frame_store = frame_store
        self.camera = camera
        self.cameras = cameras
        self.on_camera = on_camera
        self.on_capture = on_capture
        self.on_close = on_close
        self._texture = None
        self._status_text = None
        self._mode_text = None
        self._camera_combo = None
        self._rotation_combo = None

    def run(self):
        import dearpygui.dearpygui as dpg

        dpg.create_context()
        try:
            self._build(dpg)
            dpg.create_viewport(title="Math Camera", width=1040, height=760)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            while dpg.is_dearpygui_running():
                self._update(dpg)
                dpg.render_dearpygui_frame()
        finally:
            dpg.destroy_context()
            self.on_close()

    def _build(self, dpg):
        settings = self.state.get_settings()
        camera_labels = [f"{camera.name} ({camera.index})" for camera in self.cameras]
        selected_camera = next(
            (
                index
                for index, camera in enumerate(self.cameras)
                if camera.unique_id == settings.camera_id
            ),
            0,
        )

        with dpg.texture_registry():
            self._texture = dpg.add_raw_texture(
                PREVIEW_WIDTH,
                PREVIEW_HEIGHT,
                np.zeros((PREVIEW_HEIGHT, PREVIEW_WIDTH, 4), dtype=np.float32),
                format=dpg.mvFormat_Float_rgba,
            )

        with dpg.window(label="Math Camera", tag="main_window", on_close=self._close):
            with dpg.group(horizontal=True):
                dpg.add_text("Camera")
                self._camera_combo = dpg.add_combo(
                    camera_labels or ["No camera"],
                    default_value=camera_labels[selected_camera] if camera_labels else "No camera",
                    callback=self._camera_changed,
                    width=300,
                )
                dpg.add_text("Mode")
                self._mode_text = dpg.add_text(settings.mode.upper())

            with dpg.group(horizontal=True):
                dpg.add_text("Rotation")
                self._rotation_combo = dpg.add_combo(
                    ["0°", "90°", "180°", "270°"],
                    default_value=f"{settings.rotation * 90}°",
                    callback=self._rotation_changed,
                    width=100,
                )
                dpg.add_button(label="Chat mode", callback=lambda: self._set_mode("chat"))
                dpg.add_button(
                    label="Submission mode", callback=lambda: self._set_mode("submission")
                )

            dpg.add_spacer(height=8)
            dpg.add_image(self._texture, width=PREVIEW_WIDTH, height=PREVIEW_HEIGHT)
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Capture low", callback=lambda: self.on_capture(False))
                dpg.add_button(label="Capture high", callback=lambda: self.on_capture(True))
                self._status_text = dpg.add_text("Ready")
            dpg.add_text("Global capture: Ctrl+Option+M (low), Ctrl+Option+Shift+M (high)")

    def _camera_changed(self, _sender, value, _user_data=None):
        if not self.cameras or value == "No camera":
            return
        index = next(
            (
                i
                for i, camera in enumerate(self.cameras)
                if f"{camera.name} ({camera.index})" == value
            ),
            0,
        )
        self.on_camera(self.cameras[index])

    def _rotation_changed(self, _sender, value, _user_data=None):
        self.state.update_settings(rotation=int(value.rstrip("°")) // 90)

    def _set_mode(self, mode):
        self.state.update_settings(mode=mode)

    def _close(self, _sender=None, _user_data=None):
        import dearpygui.dearpygui as dpg

        if dpg.is_dearpygui_running():
            dpg.stop_dearpygui()

    def _update(self, dpg):
        frame = self.frame_store.snapshot()
        settings = self.state.get_settings()
        if frame is None:
            image = np.zeros((PREVIEW_HEIGHT, PREVIEW_WIDTH, 4), dtype=np.uint8)
            cv2.putText(
                image,
                "Waiting for camera...",
                (24, 46),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 255, 255),
                2,
            )
            image = image.astype(np.float32) / 255.0
        else:
            preview = rotate_frame(frame, settings.rotation)
            image = self._fit_preview(preview)
        dpg.set_value(self._texture, image.ravel())
        status = self.state.get_status()
        dpg.set_value(self._status_text, f"{status.state.value.title()}: {status.message}")
        dpg.set_value(self._mode_text, settings.mode.upper())

    @staticmethod
    def _fit_preview(frame):
        """Scale a BGR frame into the texture without changing its geometry."""
        frame_height, frame_width = frame.shape[:2]
        scale = min(PREVIEW_WIDTH / frame_width, PREVIEW_HEIGHT / frame_height)
        width = max(1, round(frame_width * scale))
        height = max(1, round(frame_height * scale))
        fitted = resize_frame(frame, (width, height))
        canvas = np.zeros((PREVIEW_HEIGHT, PREVIEW_WIDTH, 4), dtype=np.uint8)
        left = (PREVIEW_WIDTH - width) // 2
        top = (PREVIEW_HEIGHT - height) // 2
        canvas[top : top + height, left : left + width] = cv2.cvtColor(fitted, cv2.COLOR_BGR2RGBA)
        return canvas.astype(np.float32) / 255.0
