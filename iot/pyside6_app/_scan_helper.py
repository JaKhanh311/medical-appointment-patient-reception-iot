"""
Standalone helper: runs the QR scan loop in its own process.
Called as a subprocess from operation_page.py to avoid Qt thread conflicts on Linux.

Usage: python _scan_helper.py <camera_index> <patients_path> <appointments_path>
"""
import sys
from pathlib import Path

# Add IoT/ to path
_IOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_IOT_DIR))

from logging_utils import get_iot_logger

logger = get_iot_logger("iot.scan.helper")


def main() -> None:
    camera_index_raw = sys.argv[1] if len(sys.argv) > 1 else "0"
    patients_path = sys.argv[2] if len(sys.argv) > 2 else "patients"
    appointments_path = sys.argv[3] if len(sys.argv) > 3 else "appointment_new"

    # Convert to int if possible
    try:
        camera_index = int(camera_index_raw)
    except ValueError:
        camera_index = camera_index_raw

    from qr_scan import scan_from_camera, _load_camera_config
    config = _load_camera_config()

    try:
        result = scan_from_camera(
            camera_index=camera_index,
            patients_path=patients_path,
            appointments_path=appointments_path,
            config=config,
        )
        if result:
            print(f"[OK] Scan result: {result}")
    except Exception as exc:
        logger.exception("Scan error: %s", exc)
        print(f"[FAIL] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
