from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_CONFIGURED = False
_LOG_DIR = Path(__file__).resolve().parent / "logs"


class _NamePrefixFilter(logging.Filter):
    def __init__(self, prefix: str) -> None:
        super().__init__()
        self.prefix = prefix

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self.prefix)


def setup_iot_logging(log_dir: str | Path | None = None) -> Path:
    """Configure rotating file logging for IoT camera/app logs."""
    global _CONFIGURED, _LOG_DIR
    if log_dir is not None:
        _LOG_DIR = Path(log_dir)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    if _CONFIGURED:
        return _LOG_DIR

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    app_handler = RotatingFileHandler(
        _LOG_DIR / "app.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)
    root.addHandler(app_handler)

    camera_handler = RotatingFileHandler(
        _LOG_DIR / "camera.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    camera_handler.setLevel(logging.INFO)
    camera_handler.addFilter(_NamePrefixFilter("iot.camera"))
    camera_handler.addFilter(_NamePrefixFilter("iot.qr_scan"))
    camera_handler.setFormatter(formatter)
    root.addHandler(camera_handler)

    error_handler = RotatingFileHandler(
        _LOG_DIR / "errors.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root.addHandler(error_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    _CONFIGURED = True
    root.debug("IoT logging configured at %s", _LOG_DIR)
    return _LOG_DIR


def get_iot_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        setup_iot_logging()
    return logging.getLogger(name)
