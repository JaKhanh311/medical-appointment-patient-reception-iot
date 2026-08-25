"""
Entry point for QR Scan Studio (PySide6).
Run: python main.py
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Add IoT/ to sys.path so firebase_conn and qr_scan can be imported from pages
_APP_DIR = Path(__file__).resolve().parent        # pyside6_app/
_IOT_DIR = _APP_DIR.parent                        # IoT/

for _p in [str(_APP_DIR), str(_IOT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── High-DPI awareness (Windows) ──────────────────────────────────────────────

def _enable_high_dpi() -> None:
    if os.name != "nt":
        return
    for _fn in [
        lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)),
        lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),
        lambda: ctypes.windll.user32.SetProcessDPIAware(),
    ]:
        try:
            _fn()
            return
        except Exception:
            pass


def main() -> None:
    _enable_high_dpi()

    from logging_utils import setup_iot_logging, get_iot_logger

    setup_iot_logging()
    app_logger = get_iot_logger("iot.app")

    def _handle_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        app_logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = _handle_uncaught_exception

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from config.theme import APP_QSS
    app.setStyleSheet(APP_QSS)

    from app_controller import AppController
    controller = AppController()
    app_logger.info("QR Scan Studio started")
    controller.showFullScreen()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
