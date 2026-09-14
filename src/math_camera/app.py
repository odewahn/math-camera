import os
import platform
import subprocess
import tempfile
import threading

from math_camera import __version__

if platform.system() == "Darwin":
    import cv2

    from ApplicationServices import (
        AXIsProcessTrusted,
        AXIsProcessTrustedWithOptions,
        kAXTrustedCheckOptionPrompt,
    )

    from AppKit import (
        NSWorkspace,
        NSWorkspaceDidWakeNotification,
        NSWorkspaceWillSleepNotification,
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

    from math_camera.native_camera import NativeCameraCapture

else:
    cv2 = None
    AVCaptureDevice = None
    AVMediaTypeVideo = None
    keyboard = None
    NSWorkspace = None
    NSWorkspaceDidWakeNotification = None
    NSWorkspaceWillSleepNotification = None
    NativeCameraCapture = None


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


def list_cameras():
    ensure_supported_platform()
    cameras = get_camera_devices()

    if not cameras:
        print("No AVFoundation cameras found")
        return 1

    print("AVFoundation camera indexes:")
    print()

    for index, camera in enumerate(cameras):
        print(f"[{index}] {camera.localizedName()}")

    return 0


def get_initial_camera_index(available_indexes):
    if 0 in available_indexes:
        return 0

    return available_indexes[0]


def start_power_notification_listener(on_sleep, on_wake):
    workspace = NSWorkspace.sharedWorkspace()
    center = workspace.notificationCenter()
    observers = []

    for notification_name, callback in (
        (NSWorkspaceWillSleepNotification, on_sleep),
        (NSWorkspaceDidWakeNotification, on_wake),
    ):
        observer = center.addObserverForName_object_queue_usingBlock_(
            notification_name,
            None,
            None,
            callback,
        )
        observers.append(observer)

    return center, observers


def stop_power_notification_listener(listener):
    center, observers = listener

    for observer in observers:
        center.removeObserver_(observer)


def clear_latest_frame():
    global latest_frame

    with frame_lock:
        latest_frame = None


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

def get_native_camera_indexes():
    count = NativeCameraCapture.device_count()
    return list(range(count)) or [0]


def run(camera_index=None):
    global latest_frame

    print(f"Math Camera {__version__}")

    ensure_supported_platform()

    accessibility_ok = permission_preflight()
    available_indexes = get_native_camera_indexes()

    if camera_index is None or camera_index not in available_indexes:
        camera_index = get_initial_camera_index(available_indexes)

    camera = NativeCameraCapture(
        camera_index,
        WIDTH,
        HEIGHT,
    )
    camera.start_async()

    listener = None

    def on_sleep(_notification):
        print()
        print("macOS is going to sleep; pausing native camera session.")
        clear_latest_frame()
        camera.pause_for_sleep()

    def on_wake(_notification):
        print()
        print("macOS woke up; resuming native camera session.")
        camera.resume_async()

    power_listener = start_power_notification_listener(
        on_sleep,
        on_wake,
    )

    if accessibility_ok:
        listener = start_hotkey_listener()

    print()
    print("Math Camera")
    print("-----------")
    print(
        f"Camera:      AVFoundation device {camera_index}"
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

    last_preview = None

    try:
        while True:
            frame = camera.get_frame()

            if frame is not None:
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

                height, width = frame.shape[:2]
                scale = min(
                    700 / width,
                    700 / height,
                    1.0,
                )
                preview = cv2.resize(
                    frame,
                    None,
                    fx=scale,
                    fy=scale,
                )
                last_preview = preview
            else:
                preview = (
                    last_preview.copy()
                    if last_preview is not None
                    else None
                )

                if preview is not None:
                    cv2.putText(
                        preview,
                        "Waiting for camera...",
                        (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.9,
                        (0, 0, 255),
                        2,
                    )

            if preview is not None:
                cv2.imshow(
                    "Math Camera",
                    preview,
                )

                if hasattr(cv2, "setWindowTitle"):
                    cv2.setWindowTitle(
                        "Math Camera",
                        f"Math Camera — device {camera_index}",
                    )

            key = cv2.waitKey(30 if frame is None else 1) & 0xFF

            if key == ord("c"):
                copy_low_quality_frame_to_clipboard()

            elif key == ord("h"):
                copy_high_quality_frame_to_clipboard()

            elif key == ord("n") or key == ord("p"):
                available_indexes = get_native_camera_indexes()

                if camera_index not in available_indexes:
                    camera_index = get_initial_camera_index(
                        available_indexes
                    )
                else:
                    step = 1 if key == ord("n") else -1
                    camera_index = get_next_camera_index(
                        camera_index,
                        available_indexes,
                        step,
                    )

                clear_latest_frame()
                camera.set_camera_index(camera_index)
                print(
                    f"Switching to AVFoundation device "
                    f"{camera_index}"
                )

            elif key == ord("q") or key == 27:
                break

    except KeyboardInterrupt:
        print()
        print("Stopping Math Camera...")

    finally:
        if listener is not None:
            listener.stop()

        stop_power_notification_listener(power_listener)
        camera.close()
        cv2.destroyAllWindows()
