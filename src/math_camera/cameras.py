"""Camera identity and index-navigation helpers."""

from .state import CameraInfo


def camera_info_from_device(device, index):
    unique_id = device.uniqueID()
    name = device.localizedName()
    return CameraInfo(str(unique_id), str(name), index)


def select_camera(cameras, saved_id=None):
    if not cameras:
        return None
    return next((camera for camera in cameras if camera.unique_id == saved_id), cameras[0])


def next_camera(cameras, current_id, step=1):
    if not cameras:
        return None
    position = next((i for i, camera in enumerate(cameras) if camera.unique_id == current_id), 0)
    return cameras[(position + step) % len(cameras)]
