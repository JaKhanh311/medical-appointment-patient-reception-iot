"""
Standalone helper: opens the OpenCV camera ROI configuration window.
Called as a subprocess from camera_page.py so it gets its own message loop.

Usage: python _camera_config_helper.py <camera_index> [theme]
"""
import sys
from pathlib import Path

# Add IoT/ to path
_IOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_IOT_DIR))

from logging_utils import get_iot_logger


logger = get_iot_logger("iot.camera.helper")

def main() -> None:
    camera_index_raw = sys.argv[1] if len(sys.argv) > 1 else "0"
    theme = sys.argv[2] if len(sys.argv) > 2 else "dark"

    # Convert to int if possible
    try:
        camera_index = int(camera_index_raw)
    except ValueError:
        camera_index = camera_index_raw  # device path string on Linux

    from qr_scan import _configure_camera_preview
    try:
        config = _configure_camera_preview(camera_index, theme=theme)
        logger.info(
            "OK: ROI %s%% x %s%% | brightness=%s | exposure=%s",
            int(config["roi_scale"] * 100),
            int(config["roi_height_scale"] * 100),
            config["brightness"],
            config["exposure"],
        )
    except Exception as exc:
        logger.exception("ERROR: %s", exc)
        sys.exit(1)

if __name__ == "__main__":
    main()
