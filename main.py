#!/usr/bin/env python3

import cv2
import os
import subprocess
import tempfile
import threading

from AVFoundation import AVCaptureDevice, AVMediaTypeVideo
from pynput import keyboard


WIDTH = 1280
HEIGHT = 720
FPS = 30
LOW_QUALITY_JPEG = 55
HIGH_QUALITY_JPEG = 95

LOW_QUALITY_CAPTURE_HOTKEY = "<ctrl>+<alt>+m"
HIGH_QUALITY_CAPTURE_HOTKEY = "<ctrl>+<alt>+<shift>+m"
ROTATE_CLOCKWISE_HOTKEY = "<ctrl>+<alt>+."
ROTATE_COUNTERCLOCKWISE_HOTKEY = "<ctrl>+<alt>+,"

latest_frame = None
frame_lock = threading.Lock()
rotation_quarter_turns = 1
rotation_lock = threading.Lock()


ROTATIONS = {
    0: None,
    1: cv2.ROTATE_90_CLOCKWISE,
    2: cv2.ROTATE_180,
    3: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def get_rotation_quarter_turns():
    with rotation_lock:
        return rotation_quarter_turns


def rotate_clockwise():
    global rotation_quarter_turns

    with rotation_lock:
        rotation_quarter_turns = (rotation_quarter_turns + 1) % 4
        turns = rotation_quarter_turns

    print(f"Rotated preview/capture to {turns * 90} degrees")


def rotate_counterclockwise():
    global rotation_quarter_turns

    with rotation_lock:
        rotation_quarter_turns = (rotation_quarter_turns - 1) % 4
        turns = rotation_quarter_turns

    print(f"Rotated preview/capture to {turns * 90} degrees")


def get_camera_devices():
    return list(
        AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo)
    )


def choose_camera():
    devices = get_camera_devices()

    if not devices:
        raise RuntimeError("No cameras found")

    print()
    print("Available cameras:")
    print()

    for i, device in enumerate(devices):
        print(f"  [{i}] {device.localizedName()}")

    print()

    while True:
        try:
            raw_choice = input("Select camera [0]: ").strip()
            choice = 0 if raw_choice == "" else int(raw_choice)

            if 0 <= choice < len(devices):
                device = devices[choice]

                print()
                print(f"Selected: {device.localizedName()}")

                return choice, device

            print("Please choose one of the listed cameras.")

        except ValueError:
            print("Please enter a camera number.")


def capture_frame_to_clipboard(frame, jpeg_quality, quality_label):
    fd, path = tempfile.mkstemp(
        prefix="math-camera-",
        suffix=".jpg",
        dir="/tmp",
    )

    os.close(fd)

    try:
        success = cv2.imwrite(
            path,
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality],
        )

        if not success:
            print("Failed to encode image")
            return

        applescript = f'''
        set the clipboard to (read POSIX file "{path}" as JPEG picture)
        '''

        subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                applescript,
            ],
            check=True,
        )

        file_size_bytes = os.path.getsize(path)
        file_size_kb = file_size_bytes / 1024
        print(
            f"📷 Copied {quality_label} frame to clipboard "
            f"({file_size_kb:.1f} KB)"
        )

    except Exception as e:
        print(f"Capture failed: {e}")

    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def copy_frame_to_clipboard(jpeg_quality, quality_label):
    global latest_frame

    with frame_lock:
        if latest_frame is None:
            print("Camera frame not ready")
            return

        frame = latest_frame.copy()

    capture_frame_to_clipboard(frame, jpeg_quality, quality_label)


def copy_low_quality_frame_to_clipboard():
    copy_frame_to_clipboard(LOW_QUALITY_JPEG, "low-resolution")


def copy_high_quality_frame_to_clipboard():
    copy_frame_to_clipboard(HIGH_QUALITY_JPEG, "high-resolution")


def start_hotkey_listener():
    listener = keyboard.GlobalHotKeys(
        {
            LOW_QUALITY_CAPTURE_HOTKEY: copy_low_quality_frame_to_clipboard,
            HIGH_QUALITY_CAPTURE_HOTKEY: copy_high_quality_frame_to_clipboard,
            ROTATE_CLOCKWISE_HOTKEY: rotate_clockwise,
            ROTATE_COUNTERCLOCKWISE_HOTKEY: rotate_counterclockwise,
        }
    )

    listener.start()

    return listener


def main():
    global latest_frame

    camera_index, device = choose_camera()

    camera_name = device.localizedName()

    print()
    print(f"Opening {camera_name}...")

    cap = cv2.VideoCapture(
        camera_index,
        cv2.CAP_AVFOUNDATION,
    )

    if not cap.isOpened():
        raise RuntimeError(
            f"Could not open camera: {camera_name}"
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    listener = start_hotkey_listener()

    print()
    print("Math Camera")
    print("-----------")
    print(f"Camera:      {camera_name}")
    print("Orientation: Portrait (default)")
    print(f"Capture:     {WIDTH}x{HEIGHT}")
    print()
    print("Global capture:")
    print("  Control + Option + M           low resolution")
    print("  Control + Option + Shift + M   high resolution")
    print()
    print("Global rotation:")
    print("  Control + Option + .   rotate +90")
    print("  Control + Option + ,   rotate -90")
    print()
    print("Preview controls:")
    print("  C        low-resolution capture")
    print("  H        high-resolution capture")
    print("  Q        quit")
    print("  Esc      quit")
    print()

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                continue

            rotation = ROTATIONS[get_rotation_quarter_turns()]

            if rotation is not None:
                frame = cv2.rotate(frame, rotation)

            with frame_lock:
                latest_frame = frame.copy()

            # Scale preview while preserving aspect ratio.
            max_preview_width = 700
            max_preview_height = 700

            height, width = frame.shape[:2]

            scale = min(
                max_preview_width / width,
                max_preview_height / height,
                1.0,
            )

            preview = cv2.resize(
                frame,
                None,
                fx=scale,
                fy=scale,
            )

            cv2.imshow(
                f"Math Camera — {camera_name}",
                preview,
            )

            key = cv2.waitKey(1) & 0xFF

            if key == ord("c"):
                copy_low_quality_frame_to_clipboard()

            elif key == ord("h"):
                copy_high_quality_frame_to_clipboard()

            elif key == ord("q") or key == 27:
                break

    finally:
        listener.stop()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
