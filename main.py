#!/usr/bin/env python3

import cv2
import os
import subprocess
import tempfile
import threading

from pynput import keyboard


CAMERA_INDEX = 0

WIDTH = 1280
HEIGHT = 720
FPS = 30

PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360

HOTKEY = "<ctrl>+<alt>+m"


latest_frame = None
frame_lock = threading.Lock()


def copy_frame_to_clipboard():
    """Copy the latest camera frame to the macOS clipboard."""

    with frame_lock:
        if latest_frame is None:
            print("Camera frame not ready")
            return

        frame = latest_frame.copy()

    # AppleScript's simplest reliable way to put an image
    # on the macOS clipboard is to read it from a temporary file.
    fd, path = tempfile.mkstemp(
        prefix="ipevo-",
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
            ["/usr/bin/osascript", "-e", applescript],
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
    """Listen for the global capture shortcut."""

    listener = keyboard.GlobalHotKeys({
        HOTKEY: copy_frame_to_clipboard
    })

    listener.start()

    return listener


def main():
    global latest_frame

    cap = cv2.VideoCapture(
        CAMERA_INDEX,
        cv2.CAP_AVFOUNDATION,
    )

    if not cap.isOpened():
        raise RuntimeError("Could not open IPEVO camera")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    listener = start_hotkey_listener()

    print()
    print("IPEVO Math Camera")
    print("-----------------")
    print(f"Camera: {WIDTH}x{HEIGHT}")
    print("Global capture: Control + Option + M")
    print("Press C in the preview window to capture")
    print("Press Q or Esc to quit")
    print()

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                continue

            with frame_lock:
                latest_frame = frame.copy()

            preview = cv2.resize(
                frame,
                (PREVIEW_WIDTH, PREVIEW_HEIGHT),
            )

            cv2.imshow(
                "IPEVO Math Camera",
                preview,
            )

            key = cv2.waitKey(1) & 0xFF

            # Local capture for testing
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