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

HOTKEY = "<ctrl>+<alt>+m"

latest_frame = None
frame_lock = threading.Lock()


def choose_orientation():
    print()
    print("Orientation:")
    print()
    print("  [1] Portrait (default)")
    print("  [2] Landscape")
    print()

    while True:
        choice = input("Select orientation [1]: ").strip()

        if choice == "" or choice == "1":
            return "portrait"

        if choice == "2":
            return "landscape"

        print("Please enter 1 or 2.")


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
            choice = int(input("Select camera: "))

            if 0 <= choice < len(devices):
                device = devices[choice]

                print()
                print(f"Selected: {device.localizedName()}")

                return choice, device

            print("Please choose one of the listed cameras.")

        except ValueError:
            print("Please enter a camera number.")


def copy_frame_to_clipboard():
    global latest_frame

    with frame_lock:
        if latest_frame is None:
            print("Camera frame not ready")
            return

        frame = latest_frame.copy()

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
            [cv2.IMWRITE_JPEG_QUALITY, 90],
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

        print("📷 Copied current frame to clipboard")

    except Exception as e:
        print(f"Capture failed: {e}")

    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def start_hotkey_listener():
    listener = keyboard.GlobalHotKeys(
        {
            HOTKEY: copy_frame_to_clipboard
        }
    )

    listener.start()

    return listener


def main():
    global latest_frame

    orientation = choose_orientation()
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
    print(f"Orientation: {orientation}")
    print(f"Capture:     {WIDTH}x{HEIGHT}")
    print()
    print("Global capture:")
    print("  Control + Option + M")
    print()
    print("Preview controls:")
    print("  C        capture")
    print("  Q        quit")
    print("  Esc      quit")
    print()

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                continue

            # Physical camera turned sideways:
            # rotate image so the page appears upright.
            if orientation == "portrait":
                frame = cv2.rotate(
                    frame,
                    cv2.ROTATE_90_CLOCKWISE,
                )

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
                copy_frame_to_clipboard()

            elif key == ord("q") or key == 27:
                break

    finally:
        listener.stop()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()