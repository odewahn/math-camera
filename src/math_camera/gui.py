"""Small Dear PyGui preview and configuration panel."""

from __future__ import annotations

import cv2
import numpy as np

from .processing import resize_frame, rotate_frame, validate_roi
from .state import FrameStore, SharedState

PREVIEW_WIDTH = 960
PREVIEW_HEIGHT = 540
ROI_INTERACTION_MARGIN = 0.05


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
        self._camera_combo = None
        self._rotation_combo = None
        self._enhance_checkbox = None
        self._preview = None
        self._roi_drag = None
        self._display_rect = None

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

            with dpg.group(horizontal=True):
                dpg.add_text("Rotation")
                self._rotation_combo = dpg.add_combo(
                    ["0°", "90°", "180°", "270°"],
                    default_value=f"{settings.rotation * 90}°",
                    callback=self._rotation_changed,
                    width=100,
                )
                self._enhance_checkbox = dpg.add_checkbox(
                    label="Enhance image",
                    default_value=settings.enhance,
                    callback=self._enhancement_changed,
                )

            dpg.add_spacer(height=8)
            self._preview = dpg.add_drawlist(width=PREVIEW_WIDTH, height=PREVIEW_HEIGHT)
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Capture", callback=lambda: self.on_capture(True))
                self._status_text = dpg.add_text("Ready")
            with dpg.group(horizontal=True):
                dpg.add_button(label="Reset ROI", callback=self._reset_roi)
            dpg.add_text("Global capture: Ctrl+Option+M or Ctrl+Option+Shift+M")

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
        self.state.update_settings(
            rotation=int(value.rstrip("°")) // 90,
            roi=(0.0, 0.0, 1.0, 1.0),
        )

    def _enhancement_changed(self, _sender, value, _user_data=None):
        self.state.update_settings(enhance=bool(value))

    def _reset_roi(self, _sender=None, _user_data=None):
        self.state.update_settings(roi=(0.0, 0.0, 1.0, 1.0))

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
        dpg.delete_item(self._preview, children_only=True)
        dpg.draw_image(
            self._texture,
            (0, 0),
            (PREVIEW_WIDTH, PREVIEW_HEIGHT),
            parent=self._preview,
        )
        if frame is not None:
            self._draw_roi(dpg, preview, settings.roi)
        dpg.set_value(self._texture, image.ravel())
        status = self.state.get_status()
        dpg.set_value(self._status_text, f"{status.state.value.title()}: {status.message}")

    def _draw_roi(self, dpg, frame, roi):
        if roi is None:
            return
        frame_height, frame_width = frame.shape[:2]
        scale = min(PREVIEW_WIDTH / frame_width, PREVIEW_HEIGHT / frame_height)
        display_width = frame_width * scale
        display_height = frame_height * scale
        offset_x = (PREVIEW_WIDTH - display_width) / 2
        offset_y = (PREVIEW_HEIGHT - display_height) / 2
        self._display_rect = (offset_x, offset_y, display_width, display_height)
        x, y, width, height = roi
        left = offset_x + x * display_width
        top = offset_y + y * display_height
        right = left + width * display_width
        bottom = top + height * display_height
        dpg.draw_rectangle(
            (left, top),
            (right, bottom),
            color=(40, 220, 80, 255),
            thickness=2,
            parent=self._preview,
        )
        handles = {
            "tl": (left, top),
            "top": ((left + right) / 2, top),
            "tr": (right, top),
            "right": (right, (top + bottom) / 2),
            "br": (right, bottom),
            "bottom": ((left + right) / 2, bottom),
            "bl": (left, bottom),
            "left": (left, (top + bottom) / 2),
        }
        for handle_name, (handle_x, handle_y) in handles.items():
            dpg.draw_circle(
                (handle_x, handle_y),
                10 if len(handle_name) == 2 else 7,
                color=(40, 220, 80, 255),
                fill=(40, 220, 80, 180),
                parent=self._preview,
            )
        self._update_roi_from_mouse(dpg, left, top, right, bottom)

    def _update_roi_from_mouse(self, dpg, left, top, right, bottom):
        preview_left, preview_top = dpg.get_item_rect_min(self._preview)
        mouse_x, mouse_y = dpg.get_mouse_pos()
        mouse_x -= preview_left
        mouse_y -= preview_top
        pressed = dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
        if not pressed:
            self._roi_drag = None
            return
        if self._roi_drag is None:
            handles = {
                "tl": (left, top),
                "top": ((left + right) / 2, top),
                "tr": (right, top),
                "right": (right, (top + bottom) / 2),
                "br": (right, bottom),
                "bottom": ((left + right) / 2, bottom),
                "bl": (left, bottom),
                "left": (left, (top + bottom) / 2),
            }
            corner_handle = next(
                (
                    name
                    for name, (x, y) in handles.items()
                    if len(name) == 2 and abs(mouse_x - x) <= 24 and abs(mouse_y - y) <= 24
                ),
                None,
            )
            handle = corner_handle or next(
                (
                    name
                    for name, (x, y) in handles.items()
                    if len(name) != 2 and abs(mouse_x - x) <= 16 and abs(mouse_y - y) <= 16
                ),
                None,
            )
            if handle:
                self._roi_drag = (handle, mouse_x, mouse_y, self.state.get_settings().roi)
            elif left <= mouse_x <= right and top <= mouse_y <= bottom:
                self._roi_drag = ("move", mouse_x, mouse_y, self.state.get_settings().roi)
            return

        action, start_x, start_y, original = self._roi_drag
        _, _, display_width, display_height = self._display_rect
        x, y, width, height = original
        dx, dy = (mouse_x - start_x) / display_width, (mouse_y - start_y) / display_height
        if action == "move":
            x = min(max(-ROI_INTERACTION_MARGIN, x + dx), 1 + ROI_INTERACTION_MARGIN - width)
            y = min(max(-ROI_INTERACTION_MARGIN, y + dy), 1 + ROI_INTERACTION_MARGIN - height)
        else:
            if action in {"tl", "bl", "left"}:
                x = min(max(-ROI_INTERACTION_MARGIN, x + dx), x + width - 0.01)
                width = original[0] + original[2] - x
            if action in {"tr", "br", "right"}:
                width = min(max(0.01, width + dx), 1 + ROI_INTERACTION_MARGIN - x)
            if action in {"tl", "tr", "top"}:
                y = min(max(-ROI_INTERACTION_MARGIN, y + dy), y + height - 0.01)
                height = original[1] + original[3] - y
            if action in {"bl", "br", "bottom"}:
                height = min(max(0.01, height + dy), 1 + ROI_INTERACTION_MARGIN - y)
        self.state.update_settings(
            roi=validate_roi((x, y, width, height), allow_outside=ROI_INTERACTION_MARGIN)
        )

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
