import platform
import subprocess
import threading

from math_camera import __version__
from math_camera.cameras import camera_info_from_device, next_camera, select_camera
from math_camera.capture import CaptureRequest, CaptureWorker, MacOSClipboard
from math_camera.processing import encode_jpeg, rotate_frame
from math_camera.state import FrameStore, SharedState

if platform.system() == "Darwin":
    import cv2
    from AppKit import (
        NSWorkspace,
        NSWorkspaceDidWakeNotification,
        NSWorkspaceWillSleepNotification,
    )
    from ApplicationServices import (
        AXIsProcessTrusted,
        AXIsProcessTrustedWithOptions,
        kAXTrustedCheckOptionPrompt,
    )
    from AVFoundation import (
        AVAuthorizationStatusAuthorized,
        AVAuthorizationStatusDenied,
        AVAuthorizationStatusNotDetermined,
        AVAuthorizationStatusRestricted,
        AVCaptureDevice,
        AVMediaTypeVideo,
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
NEXT_CAMERA_HOTKEY = "<ctrl>+<alt>+n"
PREVIOUS_CAMERA_HOTKEY = "<ctrl>+<alt>+p"


latest_frame = None
frame_lock = threading.Lock()
shared_state = SharedState()
frame_store = FrameStore()
capture_worker = None

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

    status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeVideo)

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
    print("Math Camera needs Accessibility permission for its global keyboard shortcuts.")
    print()
    print("System Settings → Privacy & Security → Accessibility")
    print()
    print("Enable the terminal application you are using, then restart Math Camera.")
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
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
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
        print("Grant Accessibility permission to your terminal app, then restart Math Camera.")
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
        rotation_quarter_turns = (rotation_quarter_turns + 1) % 4
        turns = rotation_quarter_turns
        shared_state.update_settings(rotation=turns)

    print(f"Rotated preview/capture to {turns * 90} degrees")


def rotate_counterclockwise():
    global rotation_quarter_turns

    with rotation_lock:
        rotation_quarter_turns = (rotation_quarter_turns - 1) % 4
        turns = rotation_quarter_turns
        shared_state.update_settings(rotation=turns)

    print(f"Rotated preview/capture to {turns * 90} degrees")


# ---------------------------------------------------------------------------
# Camera discovery
# ---------------------------------------------------------------------------


def get_camera_devices():
    return list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo))


def get_camera_infos():
    return [
        camera_info_from_device(device, index) for index, device in enumerate(get_camera_devices())
    ]


def list_cameras():
    ensure_supported_platform()
    cameras = get_camera_devices()

    if not cameras:
        print("No AVFoundation cameras found")
        return 1

    print("AVFoundation cameras:")
    print()

    for index, camera in enumerate(cameras):
        print(f"[{index}] {camera.localizedName()} ({camera.uniqueID()})")

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
    frame_store.clear()


def get_next_camera_index(
    current_index,
    available_indexes,
    step,
):
    current_position = available_indexes.index(current_index)
    next_position = (current_position + step) % len(available_indexes)
    return available_indexes[next_position]


# ---------------------------------------------------------------------------
# Clipboard capture
# ---------------------------------------------------------------------------


def capture_frame_to_clipboard(
    frame,
    jpeg_quality,
    quality_label,
):
    try:
        payload = encode_jpeg(frame, jpeg_quality)
        MacOSClipboard().copy_jpeg(payload)
        file_size_bytes = len(payload)
        file_size_kb = file_size_bytes / 1024

        print(f"📷 Copied {quality_label} frame to clipboard ({file_size_kb:.1f} KB)")
        return True

    except Exception as error:
        print(f"Capture failed: {error}")
        return False


def copy_frame_to_clipboard(
    jpeg_quality,
    quality_label,
):
    frame = frame_store.snapshot()
    if frame is None:
        # Keep compatibility with callers that still populate the legacy
        # module-level frame directly.
        with frame_lock:
            frame = None if latest_frame is None else latest_frame.copy()
    if frame is None:
        print("Camera frame not ready")
        return False

    if capture_worker is not None:
        settings = shared_state.get_settings()
        return capture_worker.submit(CaptureRequest(frame, settings, jpeg_quality, quality_label))
    return capture_frame_to_clipboard(frame, jpeg_quality, quality_label)


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
            print(f"Sound playback failed: afplay exited with code {result.returncode}")
    except Exception as error:
        print(f"Sound playback raised an exception: {error}")


def copy_low_quality_frame_to_clipboard():
    return copy_frame_to_clipboard(
        LOW_QUALITY_JPEG,
        "low-resolution",
    )


def copy_high_quality_frame_to_clipboard():
    return copy_frame_to_clipboard(
        HIGH_QUALITY_JPEG,
        "high-resolution",
    )


# ---------------------------------------------------------------------------
# Hotkeys
# ---------------------------------------------------------------------------


def start_hotkey_listener(on_next_camera=None, on_previous_camera=None):
    hotkeys = {
        LOW_QUALITY_CAPTURE_HOTKEY: copy_low_quality_frame_to_clipboard,
        HIGH_QUALITY_CAPTURE_HOTKEY: copy_high_quality_frame_to_clipboard,
        ROTATE_CLOCKWISE_HOTKEY: rotate_clockwise,
        ROTATE_COUNTERCLOCKWISE_HOTKEY: rotate_counterclockwise,
    }
    if on_next_camera is not None:
        hotkeys[NEXT_CAMERA_HOTKEY] = on_next_camera
    if on_previous_camera is not None:
        hotkeys[PREVIOUS_CAMERA_HOTKEY] = on_previous_camera

    listener = keyboard.GlobalHotKeys(hotkeys)

    listener.start()

    return listener


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def get_native_camera_indexes():
    count = NativeCameraCapture.device_count()
    return list(range(count)) or [0]


def run(camera_index=None):
    global latest_frame, capture_worker

    print(f"Math Camera {__version__}")

    ensure_supported_platform()

    accessibility_ok = permission_preflight()
    camera_infos = get_camera_infos()
    available_indexes = [camera.index for camera in camera_infos] or [0]

    if camera_index is None or camera_index not in available_indexes:
        camera_index = get_initial_camera_index(available_indexes)

    selected_camera = next(
        (camera for camera in camera_infos if camera.index == camera_index),
        None,
    )

    camera = NativeCameraCapture(
        camera_index,
        WIDTH,
        HEIGHT,
        camera_id=selected_camera.unique_id if selected_camera else None,
    )
    camera.start_async()
    capture_worker = CaptureWorker(
        shared_state,
        MacOSClipboard(),
        lambda success: play_capture_sound() if success else play_capture_error_sound(),
    )

    listener = None
    selection_lock = threading.Lock()

    def switch_camera(step):
        nonlocal camera_index
        with selection_lock:
            camera_infos = get_camera_infos()
            if not camera_infos:
                print("No cameras available to select")
                return
            selected = select_camera(camera_infos, camera.camera_id)
            selected = next_camera(camera_infos, selected.unique_id, step)
            camera_index = selected.index
            shared_state.update_settings(camera_id=selected.unique_id)
            clear_latest_frame()
            camera.set_camera_id(selected.unique_id)
            print(f"Switching to {selected.name} (AVFoundation device {camera_index})")

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
        listener = start_hotkey_listener(
            lambda: switch_camera(1),
            lambda: switch_camera(-1),
        )

    print()
    print("Math Camera")
    print("-----------")
    print(f"Camera:      AVFoundation device {camera_index}")
    print("Orientation: Portrait (default)")
    print(f"Capture:     {WIDTH}x{HEIGHT}")
    print()

    if accessibility_ok:
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
    print("  N        next camera")
    print("  P        previous camera")
    print("  Q        quit")
    print("  Esc      quit")
    print()

    last_preview = None

    try:
        while True:
            frame = camera.get_frame()

            if frame is not None:
                with frame_lock:
                    latest_frame = frame.copy()
                frame_store.set(frame)

                preview_frame = rotate_frame(frame, get_rotation_quarter_turns())

                height, width = preview_frame.shape[:2]
                scale = min(
                    700 / width,
                    700 / height,
                    1.0,
                )
                preview = cv2.resize(
                    preview_frame,
                    None,
                    fx=scale,
                    fy=scale,
                )
                last_preview = preview
            else:
                preview = last_preview.copy() if last_preview is not None else None

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

            elif key in (ord("n"), ord("N"), ord("p"), ord("P")):
                switch_camera(1 if key in (ord("n"), ord("N")) else -1)

            elif key == ord("q") or key == 27:
                break

    except KeyboardInterrupt:
        print()
        print("Stopping Math Camera...")

    finally:
        if listener is not None:
            listener.stop()

        if capture_worker is not None:
            capture_worker.close()
            capture_worker = None
        stop_power_notification_listener(power_listener)
        camera.close()
        cv2.destroyAllWindows()
