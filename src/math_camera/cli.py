import argparse

from math_camera import __version__


def build_parser():
    parser = argparse.ArgumentParser(
        prog="math-camera",
        description="macOS document camera to clipboard utility",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="list available cameras and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    from math_camera.app import list_cameras, run

    if args.list_cameras:
        raise SystemExit(list_cameras())

    run()
