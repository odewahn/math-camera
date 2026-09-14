import os
import platform
import subprocess
import tempfile
import threading
import time

if platform.system() == "Darwin":
    import cv2

    from ApplicationServices import (
        AXIsProcessTrusted,
        AXIsProcessTrustedWithOptions,
        kAXTrustedCheckOptionPrompt,
    )

    from AVFoundation import (
        AVCaptureDevice,
        AVMediaTypeVideo,
        AVAuthorizationStatusAuthorized,
        AVAuthorizationStatusDenied,
        AVAuthorizationStatusNotDetermined,
        AVAuthorizationStatusRestricted,
    )

    from pynput import keyboard

else:
    cv2 = None
    AVCaptureDevice = None
    AVMediaTypeVideo = None
    keyboard = None


WIDTH = 1280
HEIGHT = 720
FPS = 30

LOW_QUALITY_JPEG = 55
HIGH_QUALITY_JPEG = 95
CAPTURE_SOUND_PATH = "/System/Library/Sounds/Glass.aiff"
CAPTURE_ERROR_SOUND_PATH = "/System/Library/Sounds/Basso.aiff"

LOW_QUALITY_CAPTURE_HOTKEY = "<ctrl>+<alt>+m"
HIGH_QUALITY_CAPTURE_HOTKEY = "<ctrl>+<alt>+<shift>+m"

ROTATE_CLOCKWISE_HOTKEY = "<ctrl>+<alt>+."
ROTATE_COUNTERCLOCKWISE_HOTKEY = "<ctrl>+<alt>+,"


latest_frame = None
frame_lock = threading.Lock()

rotation_quarter_turns = 1
rotation_lock = threading.Lock()


def ensure_supported_platform():
    if platform.system() != "Darwin":
        raise RuntimeError("Math Camera only supports macOS.")


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def ensure_camera_permission():
    """
    Make sure macOS camera permission has been granted before OpenCV
    attempts to open a device.

    The first call on a new machine may cause macOS to display its
    camera-permission dialog.
    """

    status = AVCaptureDevice.authorizationStatusForMediaType_(
        AVMediaTypeVideo
    )

    if status == AVAuthorizationStatusAuthorized:
        print("✓ Camera access")
        return

    if status in (
        AVAuthorizationStatusDenied,
        AVAuthorizationStatusRestricted,
    ):
        print()
        print("✗ Camera access")
        print()
        print("Math Camera does not have permission to use the camera.")
        print()
        print(
            "Open System Settings → Privacy & Security → Camera "
            "and enable your terminal application."
        )
        print()
        raise RuntimeError("Camera permission denied")

    if status == AVAuthorizationStatusNotDetermined:
        print("Requesting camera access...")

        completed = threading.Event()
        result = {"granted": False}

        def permission_callback(granted):
            result["granted"] = bool(granted)
            completed.set()

        AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            AVMediaTypeVideo,
            permission_callback,
        )

        # Wait for the user to answer the macOS dialog.
        completed.wait()

        if result["granted"]:
            print("✓ Camera access")
            return

        print()
        print("✗ Camera access")
        print()
        raise RuntimeError("Camera permission denied")


def ensure_accessibility_permission():
    """
    pynput needs Accessibility permission to receive global keyboard
    shortcuts when another application has focus.
    """

    if AXIsProcessTrusted():
        print("✓ Accessibility access")
        return True

    print("✗ Accessibility access")
    print()
    print(
        "Math Camera needs Accessibility permission for its global "
        "keyboard shortcuts."
    )
    print()
    print(
        "System Settings → Privacy & Security → Accessibility"
    )
    print()
    print(
        "Enable the terminal application you are using, then restart "
        "Math Camera."
    )
    print()

    # Ask macOS to show the Accessibility permission prompt/settings.
    AXIsProcessTrustedWithOptions_compat()

    return False


def AXIsProcessTrustedWithOptions_compat():
    """
    PyObjC representations of the AX options dictionary have varied
    slightly between releases. Keep this isolated so permission prompting
    doesn't affect the rest of the application.
    """

    try:
        AXIsProcessTrustedWithOptions(
            {kAXTrustedCheckOptionPrompt: True}
        )
    except Exception:
        # We already printed actionable instructions above.
        pass


def permission_preflight():
    print()
    print("Permissions")
    print("-----------")

    ensure_camera_permission()

    accessibility_ok = ensure_accessibility_permission()

    if not accessibility_ok:
        print("Math Camera will now exit.")
        print(
            "Grant Accessibility permission to your terminal app, "
            "then restart Math Camera."
        )
        print()
        raise RuntimeError("Accessibility permission required")

    print()

    return accessibility_ok


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------

def get_rotation_code(quarter_turns):
    if quarter_turns == 1:
        return cv2.ROTATE_90_CLOCKWISE

    if quarter_turns == 2:
        return cv2.ROTATE_180

    if quarter_turns == 3:
        return cv2.ROTATE_90_COUNTERCLOCKWISE

    return None


def get_rotation_quarter_turns():
    with rotation_lock:
        return rotation_quarter_turns


def rotate_clockwise():
    global rotation_quarter_turns

    with rotation_lock:
        rotation_quarter_turns = (
            rotation_quarter_turns + 1
        ) % 4
        turns = rotation_quarter_turns

    print(
        f"Rotated preview/capture to {turns * 90} degrees"
    )


def rotate_counterclockwise():
    global rotation_quarter_turns

    with rotation_lock:
        rotation_quarter_turns = (
            rotation_quarter_turns - 1
        ) % 4
        turns = rotation_quarter_turns

    print(
        f"Rotated preview/capture to {turns * 90} degrees"
    )


# ---------------------------------------------------------------------------
# Camera discovery
# ---------------------------------------------------------------------------

def get_camera_devices():
    return list(
        AVCaptureDevice.devicesWithMediaType_(
            AVMediaTypeVideo
        )
    )


def probe_opencv_cameras(max_index=10):
    """
    Discover which indexes OpenCV itself can actually open.

    IMPORTANT:

    AVFoundation's device ordering and OpenCV's AVFoundation camera
    indexes are not guaranteed to be the same. We therefore treat the
    two lists independently.
    """

    cameras = []

    for index in range(max_index):
        cap = cv2.VideoCapture(
            index,
            cv2.CAP_AVFOUNDATION,
        )

        if not cap.isOpened():
            cap.release()
            continue

        ok, frame = cap.read()

        if ok and frame is not None:
            height, width = frame.shape[:2]

            cameras.append(
                {
                    "opencv_index": index,
                    "width": width,
                    "height": height,
                }
            )

        cap.release()

    return cameras


def list_cameras():
    ensure_supported_platform()
    cameras = probe_opencv_cameras()

    if not cameras:
        print("No OpenCV-accessible cameras found")
        return 1

    print("OpenCV-accessible camera indexes:")
    print()

    for camera in cameras:
        print(
            f"[{camera['opencv_index']}] "
            f"{camera['width']}x{camera['height']}"
        )

    return 0


def get_available_camera_indexes():
    cameras = probe_opencv_cameras()

    if not cameras:
        raise RuntimeError(
            "OpenCV could not open any cameras."
        )

    return [camera["opencv_index"] for camera in cameras]


def get_initial_camera_index(available_indexes):
    if 0 in available_indexes:
        return 0

    return available_indexes[0]


def open_camera(camera_index):
    cap = cv2.VideoCapture(
        camera_index,
        cv2.CAP_AVFOUNDATION,
    )

    if not cap.isOpened():
        cap.release()
        raise RuntimeError(
            f"Could not open OpenCV camera index {camera_index}"
        )

    cap.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        WIDTH,
    )

    cap.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        HEIGHT,
    )

    cap.set(
        cv2.CAP_PROP_FPS,
        FPS,
    )

    return cap


def get_next_camera_index(
    current_index,
    available_indexes,
    step,
):
    current_position = available_indexes.index(current_index)
    next_position = (
        current_position + step
    ) % len(available_indexes)
    return available_indexes[next_position]


# ---------------------------------------------------------------------------
# Clipboard capture
# ---------------------------------------------------------------------------

def capture_frame_to_clipboard(
    frame,
    jpeg_quality,
    quality_label,
):
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
            [
                cv2.IMWRITE_JPEG_QUALITY,
                jpeg_quality,
            ],
        )

        if not success:
            print("Failed to encode image")
            return False

        applescript = (
            f'set the clipboard to '
            f'(read POSIX file "{path}" as JPEG picture)'
        )

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
            f"📷 Copied {quality_label} frame "
            f"to clipboard ({file_size_kb:.1f} KB)"
        )
        return True

    except Exception as error:
        print(
            f"Capture failed: {error}"
        )
        return False

    finally:
        try:
            os.unlink(path)

        except FileNotFoundError:
            pass


def copy_frame_to_clipboard(
    jpeg_quality,
    quality_label,
):
    global latest_frame

    with frame_lock:
        if latest_frame is None:
            print("Camera frame not ready")
            return False

        frame = latest_frame.copy()

    return capture_frame_to_clipboard(
        frame,
        jpeg_quality,
        quality_label,
    )


def play_capture_sound():
    play_system_sound(CAPTURE_SOUND_PATH)


def play_capture_error_sound():
    play_system_sound(CAPTURE_ERROR_SOUND_PATH)


def play_system_sound(sound_path):
    try:
        print(f"Playing sound: {sound_path}")
        result = subprocess.run(
            [
                "/usr/bin/afplay",
                sound_path,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            print(
                "Sound playback failed: "
                f"afplay exited with code {result.returncode}"
            )
    except Exception as error:
        print(f"Sound playback raised an exception: {error}")


def copy_low_quality_frame_to_clipboard():
    success = copy_frame_to_clipboard(
        LOW_QUALITY_JPEG,
        "low-resolution",
    )
    if success:
        play_capture_sound()
    else:
        play_capture_error_sound()


def copy_high_quality_frame_to_clipboard():
    success = copy_frame_to_clipboard(
        HIGH_QUALITY_JPEG,
        "high-resolution",
    )
    if success:
        play_capture_sound()
    else:
        play_capture_error_sound()


# ---------------------------------------------------------------------------
# Hotkeys
# ---------------------------------------------------------------------------

def start_hotkey_listener():
    listener = keyboard.GlobalHotKeys(
        {
            LOW_QUALITY_CAPTURE_HOTKEY:
                copy_low_quality_frame_to_clipboard,

            HIGH_QUALITY_CAPTURE_HOTKEY:
                copy_high_quality_frame_to_clipboard,

            ROTATE_CLOCKWISE_HOTKEY:
                rotate_clockwise,

            ROTATE_COUNTERCLOCKWISE_HOTKEY:
                rotate_counterclockwise,
        }
    )

    listener.start()

    return listener


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def run():
    global latest_frame

    ensure_supported_platform()

    accessibility_ok = permission_preflight()
    available_indexes = get_available_camera_indexes()
    camera_index = get_initial_camera_index(
        available_indexes
    )

    print()
    print(
        "OpenCV cameras found:"
    )

    for index in available_indexes:
        print(f"  [{index}]")

    print()
    print(
        f"Opening OpenCV camera index "
        f"{camera_index}..."
    )

    cap = open_camera(camera_index)

    listener = None

    if accessibility_ok:
        listener = start_hotkey_listener()

    print()
    print("Math Camera")
    print("-----------")
    print(
        f"Camera:      OpenCV index {camera_index}"
    )
    print(
        "Orientation: Portrait (default)"
    )
    print(
        f"Capture:     {WIDTH}x{HEIGHT}"
    )
    print()

    if accessibility_ok:
        print("Global capture:")
        print(
            "  Control + Option + M"
            "           low resolution"
        )
        print(
            "  Control + Option + Shift + M"
            "   high resolution"
        )
        print()
        print("Global rotation:")
        print(
            "  Control + Option + .   rotate +90"
        )
        print(
            "  Control + Option + ,   rotate -90"
        )
        print()

    print("Preview controls:")
    print(
        "  C        low-resolution capture"
    )
    print(
        "  H        high-resolution capture"
    )
    print(
        "  N        next camera"
    )
    print(
        "  P        previous camera"
    )
    print(
        "  Q        quit"
    )
    print(
        "  Esc      quit"
    )
    print()

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                time.sleep(0.01)
                continue

            rotation = get_rotation_code(
                get_rotation_quarter_turns()
            )

            if rotation is not None:
                frame = cv2.rotate(
                    frame,
                    rotation,
                )

            with frame_lock:
                latest_frame = frame.copy()

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
                "Math Camera",
                preview,
            )

            if hasattr(cv2, "setWindowTitle"):
                cv2.setWindowTitle(
                    "Math Camera",
                    f"Math Camera — camera {camera_index}",
                )

            key = (
                cv2.waitKey(1)
                & 0xFF
            )

            if key == ord("c"):
                copy_low_quality_frame_to_clipboard()

            elif key == ord("h"):
                copy_high_quality_frame_to_clipboard()

            elif key == ord("n"):
                next_index = get_next_camera_index(
                    camera_index,
                    available_indexes,
                    1,
                )
                next_cap = open_camera(next_index)
                cap.release()
                cap = next_cap
                camera_index = next_index
                latest_frame = None
                print(f"Switched to camera index {camera_index}")

            elif key == ord("p"):
                next_index = get_next_camera_index(
                    camera_index,
                    available_indexes,
                    -1,
                )
                next_cap = open_camera(next_index)
                cap.release()
                cap = next_cap
                camera_index = next_index
                latest_frame = None
                print(f"Switched to camera index {camera_index}")

            elif (
                key == ord("q")
                or key == 27
            ):
                break

    except KeyboardInterrupt:
        print()
        print("Stopping Math Camera...")

    finally:
        if listener is not None:
            listener.stop()

        cap.release()
        cv2.destroyAllWindows()
