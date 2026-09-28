"""Small Dear PyGui preview and configuration panel."""

from __future__ import annotations

import time

import cv2
import numpy as np

from .processing import resize_frame, rotate_frame, validate_roi
from .state import DEFAULT_ROI, FrameStore, SharedState

PREVIEW_WIDTH = 960
PREVIEW_HEIGHT = 540
PREVIEW_FPS = 15
UI_FPS = 60
ROI_MIN_SIZE = 0.01
ROI_CORNER_HIT_RADIUS = 30
ROI_EDGE_HIT_RADIUS = 24
ROI_GUIDE_DASH_LENGTH = 12
ROI_GUIDE_GAP_LENGTH = 8
ROI_SHIELD_ALPHA = 105


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
        self._roi_shift_baseline = None
        self._display_rect = None
        self._last_frame_generation = -1
        self._last_rotation = None
        self._preview_frame = None
        self._preview_image = None
        self._last_preview_update = 0.0

    def run(self):
        import dearpygui.dearpygui as dpg

        dpg.create_context()
        try:
            self._build(dpg)
            dpg.create_viewport(title="Math Camera", width=1040, height=760)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            while dpg.is_dearpygui_running():
                frame_started = time.monotonic()
                self._update(dpg)
                dpg.render_dearpygui_frame()
                elapsed = time.monotonic() - frame_started
                time.sleep(max(0, (1 / UI_FPS) - elapsed))
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
            roi=DEFAULT_ROI,
        )

    def _enhancement_changed(self, _sender, value, _user_data=None):
        self.state.update_settings(enhance=bool(value))

    def _reset_roi(self, _sender=None, _user_data=None):
        self.state.update_settings(roi=DEFAULT_ROI)

    def _close(self, _sender=None, _user_data=None):
        import dearpygui.dearpygui as dpg

        if dpg.is_dearpygui_running():
            dpg.stop_dearpygui()

    def _update(self, dpg):
        settings = self.state.get_settings()
        generation = self.frame_store.generation
        now = time.monotonic()
        rotation_changed = settings.rotation != self._last_rotation
        image_update_due = now - self._last_preview_update >= 1 / PREVIEW_FPS
        preview_changed = rotation_changed or (
            generation != self._last_frame_generation and image_update_due
        )
        if preview_changed:
            frame = self.frame_store.snapshot()
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
                self._preview_frame = None
                self._preview_image = image.astype(np.float32) / 255.0
            else:
                self._preview_frame = rotate_frame(frame, settings.rotation)
                self._preview_image = self._fit_preview(self._preview_frame)
            self._last_frame_generation = generation
            self._last_rotation = settings.rotation
            self._last_preview_update = now

        dpg.delete_item(self._preview, children_only=True)
        dpg.draw_image(
            self._texture,
            (0, 0),
            (PREVIEW_WIDTH, PREVIEW_HEIGHT),
            parent=self._preview,
        )
        if self._preview_frame is not None:
            self._draw_roi(dpg, self._preview_frame, settings.roi)
        if preview_changed:
            dpg.set_value(self._texture, self._preview_image.ravel())
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
        self._draw_roi_shield(dpg, left, top, right, bottom)
        if (
            self._shift_down(dpg)
            and dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
            and self._roi_drag
            and (self._roi_drag[0] != "move" or self._roi_shift_baseline is not None)
        ):
            self._draw_resize_guide(dpg)
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

    def _draw_roi_shield(self, dpg, left, top, right, bottom):
        """Dim everything outside the active ROI without covering its handles."""
        fill = (0, 0, 0, ROI_SHIELD_ALPHA)
        outline = (0, 0, 0, 0)
        parent = self._preview
        if top > 0:
            dpg.draw_rectangle(
                (0, 0), (PREVIEW_WIDTH, top), color=outline, fill=fill, parent=parent
            )
        if bottom < PREVIEW_HEIGHT:
            dpg.draw_rectangle(
                (0, bottom),
                (PREVIEW_WIDTH, PREVIEW_HEIGHT),
                color=outline,
                fill=fill,
                parent=parent,
            )
        if left > 0:
            dpg.draw_rectangle((0, top), (left, bottom), color=outline, fill=fill, parent=parent)
        if right < PREVIEW_WIDTH:
            dpg.draw_rectangle(
                (right, top),
                (PREVIEW_WIDTH, bottom),
                color=outline,
                fill=fill,
                parent=parent,
            )

    def _update_roi_from_mouse(self, dpg, left, top, right, bottom):
        preview_left, preview_top = dpg.get_item_rect_min(self._preview)
        mouse_x, mouse_y = dpg.get_mouse_pos()
        mouse_x -= preview_left
        mouse_y -= preview_top
        pressed = dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
        if not pressed:
            self._roi_drag = None
            self._roi_shift_baseline = None
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
            handle = self._hit_test_roi_handle(mouse_x, mouse_y, handles)
            if handle:
                self._roi_drag = (handle, mouse_x, mouse_y, self.state.get_settings().roi)
                self._roi_shift_baseline = None
            elif left <= mouse_x <= right and top <= mouse_y <= bottom:
                action = "diagonal_resize" if self._shift_down(dpg) else "move"
                self._roi_drag = (action, mouse_x, mouse_y, self.state.get_settings().roi)
                self._roi_shift_baseline = None
            return

        action, start_x, start_y, original = self._roi_drag
        _, _, display_width, display_height = self._display_rect
        if self._shift_down(dpg):
            if self._roi_shift_baseline is None:
                baseline_action = "diagonal_resize" if action == "move" else action
                self._roi_shift_baseline = (
                    baseline_action,
                    mouse_x,
                    mouse_y,
                    self.state.get_settings().roi,
                )
            action, start_x, start_y, original = self._roi_shift_baseline
            resize_handle = "tl" if action == "diagonal_resize" else action
            roi = self._shift_resize_roi(
                resize_handle,
                mouse_x,
                mouse_y,
                start_x,
                start_y,
                original,
                self._display_rect,
            )
            self.state.update_settings(roi=roi)
            return
        self._roi_shift_baseline = None
        x, y, width, height = original
        dx, dy = (mouse_x - start_x) / display_width, (mouse_y - start_y) / display_height
        if action == "move":
            x = min(max(0.0, x + dx), 1.0 - width)
            y = min(max(0.0, y + dy), 1.0 - height)
        else:
            if action in {"tl", "bl", "left"}:
                x = min(max(0.0, x + dx), x + width - ROI_MIN_SIZE)
                width = original[0] + original[2] - x
            if action in {"tr", "br", "right"}:
                width = min(max(ROI_MIN_SIZE, width + dx), 1.0 - x)
            if action in {"tl", "tr", "top"}:
                y = min(max(0.0, y + dy), y + height - ROI_MIN_SIZE)
                height = original[1] + original[3] - y
            if action in {"bl", "br", "bottom"}:
                height = min(max(ROI_MIN_SIZE, height + dy), 1.0 - y)
        self.state.update_settings(roi=validate_roi((x, y, width, height)))

    @staticmethod
    def _hit_test_roi_handle(mouse_x, mouse_y, handles):
        """Return the nearest handle under the pointer, with handles first."""
        candidates = []
        for name, (handle_x, handle_y) in handles.items():
            radius = ROI_CORNER_HIT_RADIUS if len(name) == 2 else ROI_EDGE_HIT_RADIUS
            distance_squared = (mouse_x - handle_x) ** 2 + (mouse_y - handle_y) ** 2
            if distance_squared <= radius**2:
                candidates.append((distance_squared, name))
        return min(candidates)[1] if candidates else None

    @staticmethod
    def _shift_down(dpg):
        return dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)

    @staticmethod
    def _roi_handle_points(roi, display_rect):
        offset_x, offset_y, display_width, display_height = display_rect
        x, y, width, height = roi
        left = offset_x + x * display_width
        top = offset_y + y * display_height
        right = left + width * display_width
        bottom = top + height * display_height
        return {
            "tl": (left, top),
            "top": ((left + right) / 2, top),
            "tr": (right, top),
            "right": (right, (top + bottom) / 2),
            "br": (right, bottom),
            "bottom": ((left + right) / 2, bottom),
            "bl": (left, bottom),
            "left": (left, (top + bottom) / 2),
        }

    @staticmethod
    def _opposite_handle(handle):
        return {
            "tl": "br",
            "top": "bottom",
            "tr": "bl",
            "right": "left",
            "br": "tl",
            "bottom": "top",
            "bl": "tr",
            "left": "right",
        }[handle]

    @classmethod
    def _resize_line(cls, handle, roi, display_rect):
        handles = cls._roi_handle_points(roi, display_rect)
        opposite = cls._opposite_handle(handle)
        origin = handles[opposite]
        direction = (
            handles[handle][0] - origin[0],
            handles[handle][1] - origin[1],
        )
        return origin, direction

    @classmethod
    def _shift_resize_roi(
        cls,
        handle,
        mouse_x,
        mouse_y,
        start_x,
        start_y,
        roi,
        display_rect,
    ):
        handles = cls._roi_handle_points(roi, display_rect)
        opposite = cls._opposite_handle(handle)
        anchor = handles[handle]
        moving_start = handles[opposite]
        direction = (moving_start[0] - anchor[0], moving_start[1] - anchor[1])
        direction_length_squared = direction[0] ** 2 + direction[1] ** 2
        if direction_length_squared == 0:
            return roi
        mouse_vector = (mouse_x - start_x, mouse_y - start_y)
        scale = (
            mouse_vector[0] * direction[0] + mouse_vector[1] * direction[1]
        ) / direction_length_squared
        moving = (
            moving_start[0] + scale * direction[0],
            moving_start[1] + scale * direction[1],
        )
        offset_x, offset_y, frame_width, frame_height = display_rect
        moving_x = (moving[0] - offset_x) / frame_width
        moving_y = (moving[1] - offset_y) / frame_height
        x, y, width, height = roi
        right, bottom = x + width, y + height
        if handle in {"tl", "bl", "left"}:
            moving_x = min(max(x + ROI_MIN_SIZE, moving_x), 1.0)
            x, width = x, moving_x - x
        elif handle in {"tr", "br", "right"}:
            moving_x = min(max(0.0, moving_x), right - ROI_MIN_SIZE)
            x, width = moving_x, right - moving_x
        if handle in {"tl", "tr", "top"}:
            moving_y = min(max(y + ROI_MIN_SIZE, moving_y), 1.0)
            y, height = y, moving_y - y
        elif handle in {"bl", "br", "bottom"}:
            moving_y = min(max(0.0, moving_y), bottom - ROI_MIN_SIZE)
            y, height = moving_y, bottom - moving_y
        return validate_roi((x, y, width, height))

    def _draw_resize_guide(self, dpg):
        if self._roi_shift_baseline is not None:
            action, _start_x, _start_y, original = self._roi_shift_baseline
        else:
            action, _start_x, _start_y, original = self._roi_drag
        if action == "diagonal_resize":
            action = "tl"
        origin, direction = self._resize_line(action, original, self._display_rect)
        direction_length = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
        if direction_length == 0:
            return
        unit_x, unit_y = direction[0] / direction_length, direction[1] / direction_length
        candidates = []
        for edge, value in (("left", 0), ("right", PREVIEW_WIDTH)):
            if unit_x:
                scale = (value - origin[0]) / unit_x
                point_y = origin[1] + scale * unit_y
                if 0 <= point_y <= PREVIEW_HEIGHT:
                    candidates.append((scale, (value, point_y)))
        for edge, value in (("top", 0), ("bottom", PREVIEW_HEIGHT)):
            if unit_y:
                scale = (value - origin[1]) / unit_y
                point_x = origin[0] + scale * unit_x
                if 0 <= point_x <= PREVIEW_WIDTH:
                    candidates.append((scale, (point_x, value)))
        if len(candidates) < 2:
            return
        candidates.sort(key=lambda item: item[0])
        start, end = candidates[0][1], candidates[-1][1]
        total_length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
        if total_length == 0:
            return
        unit_x = (end[0] - start[0]) / total_length
        unit_y = (end[1] - start[1]) / total_length
        distance = 0
        while distance < total_length:
            dash_end = min(distance + ROI_GUIDE_DASH_LENGTH, total_length)
            dpg.draw_line(
                (start[0] + distance * unit_x, start[1] + distance * unit_y),
                (start[0] + dash_end * unit_x, start[1] + dash_end * unit_y),
                color=(255, 210, 70, 220),
                thickness=2,
                parent=self._preview,
            )
            distance += ROI_GUIDE_DASH_LENGTH + ROI_GUIDE_GAP_LENGTH

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
