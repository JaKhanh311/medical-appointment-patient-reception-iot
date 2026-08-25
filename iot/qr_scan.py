import numpy as np
def _draw_multiline_centered_pil(img: np.ndarray, text: str, y: int, size=24, color=(0, 200, 0), line_gap=10) -> np.ndarray:
    """Vẽ nhiều dòng Unicode canh giữa ngang trên frame bằng Pillow."""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    font = _get_font(size)
    current_y = y
    for line in str(text or '').splitlines():
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = max(0, (img.shape[1] - text_w) // 2)
        draw.text((x, current_y), line, font=font, fill=color)
        current_y += text_h + line_gap
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
import os

# Set Qt env before importing cv2 — Linux only (xcb not available on Windows).
if os.name != "nt":
    # CRITICAL: On Linux when running inside PySide6 app, OpenCV's Qt backend
    # conflicts with PySide6's Qt event loop. Force OpenCV to use GTK instead.
    os.environ["OPENCV_VIDEOIO_PRIORITY_GSTREAMER"] = "0"
    # Tell OpenCV highgui to NOT use Qt (use GTK or fallback)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = ""
    os.environ.setdefault("DISPLAY", ":0")

    if not os.environ.get("QT_QPA_FONTDIR"):
        for _font_dir in (
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/freefont",
            "/usr/share/fonts",
        ):
            if os.path.isdir(_font_dir):
                os.environ["QT_QPA_FONTDIR"] = _font_dir
                break

import threading
import time
import base64
import logging
import re
import textwrap
from queue import Queue, Empty, Full
import cv2
import numpy as np
from pyzbar import pyzbar
from pyzbar.pyzbar import ZBarSymbol
from PIL import Image, ImageDraw, ImageFont
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv
from typing import Any, Callable
import json
from pathlib import Path
from firebase_conn import (
    get_db_ref,
    get_patient,
    get_appointment,
    update_patient_status,
    update_appointment_status,
    get_appointments_for_patient,
    update_global_appointment_status,
    update_global_appointment_fields,
    add_patient_to_queue,
)

from logging_utils import get_iot_logger

camera_lock = threading.Lock()
logger = get_iot_logger("iot.qr_scan")


# Config file cho camera settings
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "camera_config.json"

CAMERA_OPEN_ATTEMPTS = 5
CAMERA_OPEN_RETRY_SEC = 0.25
CAMERA_FIRST_FRAME_ATTEMPTS = 12
CAMERA_FIRST_FRAME_RETRY_SEC = 0.06

TB_BRIGHTNESS  = "01 Brightness   "
TB_CONTRAST    = "02 Contrast     "
TB_EXPOSURE    = "03 Exposure     "
TB_GAIN        = "04 Gain         "
TB_FOCUS       = "05 Focus (F)    "
TB_SHARPNESS   = "06 Sharpness    "
TB_SATURATION  = "07 Saturation   "
TB_ROI_SIZE    = "08 ROI Width %  "
TB_ROI_HEIGHT  = "09 ROI Height % "

PREVIEW_WINDOW = "Camera Config"

CONFIG_CONTROL_SPECS = [
    {"key": "auto_camera", "label": "Auto Camera", "min": 0, "max": 1, "step": 1},
    {"key": "brightness", "label": "Brightness", "min": 0, "max": 100, "step": 1},
    {"key": "contrast", "label": "Contrast", "min": 0, "max": 300, "step": 5},
    {"key": "exposure", "label": "Exposure", "min": 0, "max": 20, "step": 1},
    {"key": "gain", "label": "Gain", "min": 0, "max": 100, "step": 1},
    {"key": "focus", "label": "Focus", "min": 0, "max": 255, "step": 5},
    {"key": "sharpness", "label": "Sharpness", "min": 0, "max": 100, "step": 1},
    {"key": "saturation", "label": "Saturation", "min": 0, "max": 200, "step": 2},
    {"key": "roi_width", "label": "ROI Width %", "min": 10, "max": 100, "step": 1},
    {"key": "roi_height", "label": "ROI Height %", "min": 10, "max": 100, "step": 1},
]

KEY_REPEAT_INTERVAL = 0.09


CAMERA_CONFIG_UI_THEME = {
    "dark": {
        "canvas_bg": "#0A0A0A",
        "sidebar_bg": "#161616",
        "sidebar_border": "#414141",
        "title": "#22C55E",
        "text": "#E5E7EB",
        "label": "#D1D5DB",
        "secondary": "#9CA3AF",
        "disabled": "#6B7280",
        "selection_bg": "#263426",
        "selection_border": "#22C55E",
        "bar_bg": "#373737",
        "bar_fill": "#16A34A",
        "knob": "#F3F4F6",
        "footer_bg": "#101010",
        "footer_border": "#3C3C3C",
    },
    "light": {
        "canvas_bg": "#FFFFFF",
        "sidebar_bg": "#FFFFFF",
        "sidebar_border": "#D1D5DB",
        "title": "#111827",
        "text": "#1F2937",
        "label": "#374151",
        "secondary": "#6B7280",
        "disabled": "#9CA3AF",
        "selection_bg": "#F9FAFB",
        "selection_border": "#1F2937",
        "bar_bg": "#E5E7EB",
        "bar_fill": "#374151",
        "knob": "#111827",
        "footer_bg": "#F9FAFB",
        "footer_border": "#E5E7EB",
    },
}

AUTO_CAMERA_TARGET_LUMA = 134.0
AUTO_CAMERA_LUMA_LOW = 82.0
AUTO_CAMERA_LUMA_HIGH = 188.0
AUTO_CAMERA_SHARPNESS_LOW = 85.0
AUTO_CAMERA_SHARPNESS_RECOVER = 115.0
AUTO_CAMERA_SHADOW_RATIO_HIGH = 0.38
AUTO_CAMERA_HIGHLIGHT_RATIO_HIGH = 0.18
AUTO_CAMERA_REFOCUS_MIN_SEC = 3.0
AUTO_CAMERA_REEXPOSE_MIN_SEC = 4.5
AUTO_CAMERA_PREVIEW_LUMA_DEADBAND = 8.0
AUTO_CAMERA_PREVIEW_ALPHA_MAX_STEP = 0.035
AUTO_CAMERA_PREVIEW_BETA_MAX_STEP = 3.5
AUTO_CAMERA_MIN_LOCAL_CONTRAST_FOR_AF = 18.0
AUTO_CAMERA_MIN_LOCAL_CONTRAST_FOR_AE = 16.0

AUTO_CAMERA_STATE_DEFAULTS = {
    "alpha": 1.08,
    "beta": 10.0,
    "blur_count": 0.0,
    "dark_count": 0.0,
    "bright_count": 0.0,
    "last_af_kick": 0.0,
    "last_ae_kick": 0.0,
    "mean_luma": AUTO_CAMERA_TARGET_LUMA,
    "sharpness": 0.0,
    "shadow_ratio": 0.0,
    "highlight_ratio": 0.0,
    "local_contrast": 0.0,
}

def _hex_to_bgr(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return (255, 255, 255)
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return (b, g, r)


def _setup_qt_ui_env() -> None:
    """Keep for safety when function is called from embedded environments."""
    if not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def _load_camera_config() -> dict:
    """Load camera config from file or return defaults."""
    defaults = _get_default_camera_config()
    candidates = [CONFIG_FILE]
    legacy_config = Path.cwd() / "camera_config.json"
    try:
        if legacy_config.resolve() != CONFIG_FILE.resolve():
            candidates.append(legacy_config)
    except Exception:
        candidates.append(legacy_config)

    for config_path in candidates:
        if not config_path.exists():
            continue
        try:
            with config_path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                merged = dict(defaults)
                merged.update(loaded)
                # Nếu đọc từ file legacy, migrate về file chuẩn của module.
                if config_path != CONFIG_FILE and not CONFIG_FILE.exists():
                    _save_camera_config(merged)
                return merged
            logger.warning(
                "camera_config không hợp lệ tại %s (không phải object), bỏ qua.",
                config_path,
            )
        except Exception as exc:
            logger.warning("Lỗi đọc camera config (%s): %s", config_path, exc)
    return defaults


def _reset_camera_config() -> dict:
    """Reset camera config to factory defaults."""
    default_config = _get_default_camera_config()
    _save_camera_config(default_config)
    return default_config


def _get_default_camera_config() -> dict:
    """Get factory default config (internal helper for reset)."""
    default_index = "0" if os.name == "nt" else "/dev/video0"
    return {
        "camera_index": default_index,
        "auto_camera": True,
        "brightness": 80,
        "contrast": 1.15,
        "gain": 15,
        "exposure": -1,
        "focus": 20,
        "sharpness": 70,
        "saturation": 200,
        "roi_scale": 0.7,
        "roi_height_scale": 0.7,
        "camera_width": 1280,
        "camera_height": 720,
        "camera_fps": 30,
        "custom_message": "Mã lịch hẹn đã bị hủy hoặc quá hạn vui lòng kiểm tra lại",
    }


def _save_camera_config(config: dict) -> None:
    """Save camera config to file."""
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Lỗi lưu config: %s", e)

def _draw_hud_panel(img, W, H, last_message=""):
    panel_h = int(H * 0.22)

    y0 = H - panel_h

    # nền mờ đen
    overlay = img.copy()
    cv2.rectangle(overlay, (0, y0), (W, H), (0, 0, 0), -1)
    img = cv2.addWeighted(overlay, 0.4, img, 0.6, 0)

    # text trạng thái
    cv2.putText(
        img,
        f"STATUS: {last_message}",
        (20, y0 + 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 0),
        2
    )

    cv2.putText(
        img,
        "Q = Quit | D = Reset | P = Preset",
        (20, y0 + 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (180, 180, 180),
        2
    )

    return img


def _build_camera_control_state(config: dict) -> dict:
    return {
        "auto_camera": 1 if bool(config.get("auto_camera", True)) else 0,
        "brightness": int(config.get("brightness", 80)),
        "contrast": int(round(float(config.get("contrast", 1.15)) * 100)),
        "exposure": int(config.get("exposure", -1)) + 10,
        "gain": int(config.get("gain", 15)),
        "focus": int(config.get("focus", 20)),
        "sharpness": int(config.get("sharpness", 70)),
        "saturation": int(config.get("saturation", 200)),
        "roi_width": int(round(float(config.get("roi_scale", 0.7)) * 100)),
        "roi_height": int(round(float(config.get("roi_height_scale", config.get("roi_scale", 0.7))) * 100)),
    }


def _control_state_to_config_values(state: dict) -> dict:
    return {
        "auto_camera": bool(state["auto_camera"]),
        "brightness": int(state["brightness"]),
        "contrast": float(state["contrast"]) / 100.0,
        "exposure": int(state["exposure"]) - 10,
        "gain": int(state["gain"]),
        "focus": int(state["focus"]),
        "sharpness": int(state["sharpness"]),
        "saturation": int(state["saturation"]),
        "roi_scale": max(0.1, float(state["roi_width"]) / 100.0),
        "roi_height_scale": max(0.1, float(state["roi_height"]) / 100.0),
    }


def _format_camera_control_value(key: str, value: int) -> str:
    if key == "auto_camera":
        return "AUTO" if int(value) == 1 else "MANUAL"
    if key == "contrast":
        return f"{value / 100.0:.2f}"
    if key == "exposure":
        return f"{value - 10}"
    if key in {"roi_width", "roi_height"}:
        return f"{value}%"
    return f"{value}"


def _adjust_camera_control_value(state: dict, selected_idx: int, direction: int) -> None:
    spec = CONFIG_CONTROL_SPECS[selected_idx]
    next_value = state[spec["key"]] + (spec["step"] * direction)
    state[spec["key"]] = max(spec["min"], min(spec["max"], next_value))


def _set_camera_auto_mode(cap, enabled: bool) -> None:
    try:
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if enabled else 0)
    except Exception:
        pass

    try:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3 if enabled else 1)
    except Exception:
        try:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if enabled else 0.25)
        except Exception:
            pass


def _use_windows_native_camera_defaults(auto_camera_enabled: bool) -> bool:
    """On Windows auto mode, let the camera driver keep its own defaults."""
    return os.name == "nt" and bool(auto_camera_enabled)


def _build_auto_camera_state() -> dict[str, float]:
    return dict(AUTO_CAMERA_STATE_DEFAULTS)


def _ensure_auto_camera_state(state: dict[str, float]) -> dict[str, float]:
    for key, value in AUTO_CAMERA_STATE_DEFAULTS.items():
        state.setdefault(key, value)
    return state


def _pulse_auto_exposure(cap) -> None:
    pairs = ((1, 3), (0.25, 0.75)) if os.name == "nt" else ((0.25, 0.75), (1, 3))
    for off_value, on_value in pairs:
        try:
            off_ok = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, off_value)
            on_ok = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, on_value)
            if off_ok or on_ok:
                return
        except Exception:
            continue


def _rebalance_auto_exposure(cap, state: dict[str, float]) -> None:
    state = _ensure_auto_camera_state(state)
    mean_luma = float(state.get("mean_luma", AUTO_CAMERA_TARGET_LUMA))
    shadow_ratio = float(state.get("shadow_ratio", 0.0))
    highlight_ratio = float(state.get("highlight_ratio", 0.0))
    local_contrast = float(state.get("local_contrast", 0.0))
    now = time.monotonic()

    too_dark = mean_luma < AUTO_CAMERA_LUMA_LOW or shadow_ratio > AUTO_CAMERA_SHADOW_RATIO_HIGH
    too_bright = mean_luma > AUTO_CAMERA_LUMA_HIGH or highlight_ratio > AUTO_CAMERA_HIGHLIGHT_RATIO_HIGH

    if (
        local_contrast < AUTO_CAMERA_MIN_LOCAL_CONTRAST_FOR_AE
        and AUTO_CAMERA_LUMA_LOW - 10.0 <= mean_luma <= AUTO_CAMERA_LUMA_HIGH + 10.0
    ):
        state["dark_count"] = max(0.0, state["dark_count"] - 0.8)
        state["bright_count"] = max(0.0, state["bright_count"] - 0.8)
        return

    if too_dark:
        state["dark_count"] += 1.0
        state["bright_count"] = max(0.0, state["bright_count"] - 0.6)
    elif too_bright:
        state["bright_count"] += 1.0
        state["dark_count"] = max(0.0, state["dark_count"] - 0.6)
    else:
        state["dark_count"] = max(0.0, state["dark_count"] - 0.8)
        state["bright_count"] = max(0.0, state["bright_count"] - 0.8)
        return

    if max(state["dark_count"], state["bright_count"]) < 10.0:
        return
    if (now - state["last_ae_kick"]) < AUTO_CAMERA_REEXPOSE_MIN_SEC:
        return

    state["last_ae_kick"] = now
    state["dark_count"] = 0.0
    state["bright_count"] = 0.0
    _pulse_auto_exposure(cap)


def _draw_config_text_view(frame: np.ndarray, state: dict, selected_idx: int, theme: str = "dark") -> np.ndarray:
    """Compose a single-window preview with a large camera view and a readable config sidebar."""
    palette = CAMERA_CONFIG_UI_THEME.get(theme, CAMERA_CONFIG_UI_THEME["dark"])
    frame_h, frame_w = frame.shape[:2]
    sidebar_w = 380
    row_y = 136
    row_h = 58
    control_block_bottom = row_y + (len(CONFIG_CONTROL_SPECS) * row_h)
    footer_top_padding = 12
    footer_block_height = 100
    min_sidebar_height = control_block_bottom + footer_top_padding + footer_block_height + 16
    canvas_h = max(720, frame_h, min_sidebar_height)
    canvas_w = max(1280, frame_w + sidebar_w)
    camera_w = canvas_w - sidebar_w
    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    canvas[:] = _hex_to_bgr(palette["canvas_bg"])

    scale = min(camera_w / frame_w, canvas_h / frame_h)
    resized_w = max(1, int(frame_w * scale))
    resized_h = max(1, int(frame_h * scale))
    resized = cv2.resize(frame, (resized_w, resized_h))
    camera_x = (camera_w - resized_w) // 2
    camera_y = (canvas_h - resized_h) // 2
    canvas[camera_y:camera_y + resized_h, camera_x:camera_x + resized_w] = resized

    divider_x = camera_w
    cv2.rectangle(canvas, (divider_x, 0), (canvas_w - 1, canvas_h - 1), _hex_to_bgr(palette["sidebar_bg"]), -1)
    cv2.line(canvas, (divider_x, 0), (divider_x, canvas_h), _hex_to_bgr(palette["sidebar_border"]), 1)

    x0 = divider_x + 22
    cv2.putText(canvas, "Camera Config", (x0, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, _hex_to_bgr(palette["title"]), 2)
    cv2.putText(canvas, "Up/Down: chon | Left/Right hoac J/L: chinh", (x0, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.46, _hex_to_bgr(palette["secondary"]), 1)
    cv2.putText(canvas, "M: toggle Auto Camera nhanh", (x0, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.44, _hex_to_bgr(palette["secondary"]), 1)
    cv2.putText(canvas, "ESC: Save | R: Reset | D: Default | P: Preset", (x0, 102), cv2.FONT_HERSHEY_SIMPLEX, 0.44, _hex_to_bgr(palette["secondary"]), 1)

    bar_w = sidebar_w - 84
    for idx, spec in enumerate(CONFIG_CONTROL_SPECS):
        top = row_y + idx * row_h
        bottom = top + 42
        left = divider_x + 12
        right = canvas_w - 16
        if idx == selected_idx:
            cv2.rectangle(canvas, (left, top - 10), (right, bottom + 6), _hex_to_bgr(palette["selection_bg"]), -1)
            cv2.rectangle(canvas, (left, top - 10), (right, bottom + 6), _hex_to_bgr(palette["selection_border"]), 1)

        value = state[spec["key"]]
        ratio = (value - spec["min"]) / max(1, (spec["max"] - spec["min"]))
        cv2.putText(canvas, spec["label"], (x0, top), cv2.FONT_HERSHEY_SIMPLEX, 0.54, _hex_to_bgr(palette["label"]), 1)
        cv2.putText(canvas, _format_camera_control_value(spec["key"], value), (canvas_w - 100, top), cv2.FONT_HERSHEY_SIMPLEX, 0.58, _hex_to_bgr(palette["text"]), 1)
        bar_y = top + 14
        cv2.rectangle(canvas, (x0, bar_y), (x0 + bar_w, bar_y + 10), _hex_to_bgr(palette["bar_bg"]), -1)
        cv2.rectangle(canvas, (x0, bar_y), (x0 + int(bar_w * ratio), bar_y + 10), _hex_to_bgr(palette["bar_fill"]), -1)
        knob_x = x0 + int(bar_w * ratio)
        cv2.circle(canvas, (knob_x, bar_y + 5), 6, _hex_to_bgr(palette["knob"]), -1)

    footer_y = canvas_h - 84
    footer_top = max(control_block_bottom + footer_top_padding, footer_y - 16)
    cv2.rectangle(canvas, (divider_x + 12, footer_top), (canvas_w - 16, canvas_h - 16), _hex_to_bgr(palette["footer_bg"]), -1)
    cv2.rectangle(canvas, (divider_x + 12, footer_top), (canvas_w - 16, canvas_h - 16), _hex_to_bgr(palette["footer_border"]), 1)
    cv2.putText(canvas, "Auto Camera: camera tu canh sang/net", (x0, footer_y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.48, _hex_to_bgr(palette["text"]), 1)
    cv2.putText(canvas, "Manual: dieu chinh tung thong so chi tiet", (x0, footer_y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.48, _hex_to_bgr(palette["disabled"]), 1)
    return canvas


def _open_camera(camera_index):
    if isinstance(camera_index, str):
        raw = camera_index.strip()
        if raw.startswith("/dev/video"):
            target = raw
        elif raw.isdigit():
            target = int(raw)
        elif not raw:
            target = 0
        else:
            try:
                target = int(raw)
            except (ValueError, TypeError):
                target = 0
    else:
        try:
            target = int(camera_index)
        except (ValueError, TypeError):
            target = 0

    def _try_open(source: Any, backend: int | None):
        try:
            cap = cv2.VideoCapture(source) if backend is None else cv2.VideoCapture(source, backend)
        except Exception:
            return None
        if cap is not None and cap.isOpened():
            return cap
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
        return None

    # Windows: prefer MSMF then DSHOW, then generic.
    if os.name == "nt":
        for backend_name in ("CAP_MSMF", "CAP_DSHOW"):
            backend = getattr(cv2, backend_name, None)
            if backend is None:
                continue
            cap = _try_open(target, backend)
            if cap is not None:
                return cap
        cap = _try_open(target, None)
        if cap is not None:
            return cap
        # Last resort: return a best-effort capture object so caller can decide.
        try:
            cap = cv2.VideoCapture(target)
            if cap is not None:
                return cap
        except Exception:
            pass
        # Return a dummy released capture rather than None so caller's .isOpened() still works.
        return cv2.VideoCapture()

    # Linux/Pi: try multiple backends and device indexes for USB cameras.
    candidates = _get_linux_camera_candidates(target)
    seen: set[tuple[str, str]] = set()
    for source, backend in candidates:
        key = (str(source), str(backend))
        if key in seen:
            continue
        seen.add(key)
        cap = _try_open(source, backend)
        if cap is not None:
            print(f"[INFO] Opened camera: {source} backend={backend}")
            return cap
        else:
            print(f"[WARN] Failed to open camera: {source} backend={backend}")
    # Last resort.
    print(f"[ERROR] All attempts to open camera failed, fallback to cv2.VideoCapture({target})")
    try:
        cap = cv2.VideoCapture(target)
        if cap is not None:
            return cap
    except Exception:
        pass
    return cv2.VideoCapture()


def _get_linux_camera_candidates(target):
    """Sinh ra các cặp (source, backend) để thử mở camera USB trên Linux tối ưu nhất."""
    cap_v4l2 = getattr(cv2, "CAP_V4L2", None)
    cap_gst = getattr(cv2, "CAP_GSTREAMER", None)
    primary_backends = [cap_v4l2, cap_gst, None]
    candidates = []
    # Thử target với các backend
    for backend in primary_backends:
        candidates.append((target, backend))
    # Nếu là /dev/videoX, thử cả số X
    if isinstance(target, str) and target.startswith("/dev/video"):
        suffix = target.replace("/dev/video", "", 1)
        if suffix.isdigit():
            idx = int(suffix)
            for backend in primary_backends:
                candidates.append((idx, backend))
    # Nếu là số, thử cả /dev/videoX
    elif isinstance(target, int) and target >= 0:
        dev_path = f"/dev/video{target}"
        for backend in primary_backends:
            candidates.append((dev_path, backend))
    # Thử thêm các device index phổ biến (0-4)
    for idx in range(5):
        for backend in primary_backends:
            candidates.append((idx, backend))
            candidates.append((f"/dev/video{idx}", backend))
    return candidates


def _hard_release_camera(cap, window_names: tuple[str, ...] = ()):
    try:
        if cap is not None:
            cap.release()
    except:
        pass

    if window_names:
        for window_name in window_names:
            try:
                cv2.destroyWindow(window_name)
            except Exception:
                pass
    else:
        cv2.destroyAllWindows()

    # Flush pending UI events so next open does not inherit stale key/window state.
    for _ in range(3):
        try:
            cv2.waitKey(1)
        except Exception:
            pass
    time.sleep(0.2)

def _configure_camera_preview(camera_index: int = 0, theme: str = "dark") -> dict:

    config = _load_camera_config()
    auto_camera_enabled = bool(config.get("auto_camera", True))
    use_windows_native_defaults = _use_windows_native_camera_defaults(auto_camera_enabled)
    cap, frame = _open_and_warmup_camera(
        camera_index=camera_index,
        config=config,
        auto_camera_enabled=auto_camera_enabled,
        use_windows_native_defaults=use_windows_native_defaults,
        default_width=1280,
        default_height=720,
        default_fps=30,
        prefer_mjpg=False,
    )

    _setup_qt_ui_env()
    cv2.namedWindow(PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(PREVIEW_WINDOW, 1200, 780)
    logger.info("ESC = Save | R = Reset | D = Default | P = QR Preset | M = Toggle Auto Camera")

    last_values = {}
    selected_idx = 0
    control_state = _build_camera_control_state(config)
    auto_preview_state = _build_auto_camera_state()
    prev_auto_camera = None
    last_nav_key = None
    last_nav_at = 0.0

    def apply_if_changed(name, value, prop):
        if last_values.get(name) != value:
            cap.set(prop, value)
            last_values[name] = value

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_h, frame_w = frame.shape[:2]
            current_values = _control_state_to_config_values(control_state)
            brightness = current_values["brightness"]
            contrast = current_values["contrast"]
            exposure = current_values["exposure"]
            gain = current_values["gain"]
            focus = current_values["focus"]
            sharpness = current_values["sharpness"]
            saturation = current_values["saturation"]
            roi_scale = current_values["roi_scale"]
            roi_height_scale = current_values["roi_height_scale"]
            auto_camera_enabled = bool(current_values["auto_camera"])
            use_windows_native_defaults = _use_windows_native_camera_defaults(auto_camera_enabled)
            roi_w = int(frame_w * roi_scale)
            roi_h = int(frame_h * roi_height_scale)
            roi_x = (frame_w - roi_w) // 2
            roi_y = (frame_h - roi_h) // 2
            roi = (roi_x, roi_y, roi_w, roi_h)

            if prev_auto_camera is None or prev_auto_camera != auto_camera_enabled:
                if not use_windows_native_defaults:
                    _set_camera_auto_mode(cap, auto_camera_enabled)
                last_values.clear()
                prev_auto_camera = auto_camera_enabled
                if auto_camera_enabled:
                    auto_preview_state = _build_auto_camera_state()

            # ----- Apply ONLY when changed -----
            if not auto_camera_enabled:
                apply_if_changed("exposure",   exposure,   cv2.CAP_PROP_EXPOSURE)
                apply_if_changed("gain",       gain,       cv2.CAP_PROP_GAIN)
                apply_if_changed("focus",      focus,      cv2.CAP_PROP_FOCUS)
                apply_if_changed("sharpness",  sharpness,  cv2.CAP_PROP_SHARPNESS)
                apply_if_changed("saturation", saturation, cv2.CAP_PROP_SATURATION)

            # ----- Software brightness / contrast -----
            if auto_camera_enabled:
                auto_alpha, auto_beta, auto_sharpness = _auto_adjust_exposure_for_roi(
                    frame,
                    roi,
                    auto_preview_state,
                )
                if not use_windows_native_defaults:
                    _rebalance_auto_exposure(cap, auto_preview_state)
                    _kick_autofocus_if_blurry(cap, auto_preview_state, auto_sharpness)
                frame = cv2.convertScaleAbs(frame, alpha=auto_alpha, beta=auto_beta)
            else:
                frame = cv2.convertScaleAbs(frame, alpha=contrast, beta=brightness - 50)

            # ----- ROI preview -----
            cv2.rectangle(frame, (roi_x, roi_y), (roi_x + roi_w, roi_y + roi_h), (0, 255, 0), 3)

            preview_frame = _draw_config_text_view(frame, control_state, selected_idx, theme=theme)

            cv2.imshow(PREVIEW_WINDOW, preview_frame)

            key = cv2.waitKeyEx(1)
            now = time.monotonic()

            # SAVE
            if key == 27:
                config.update(_control_state_to_config_values(control_state))
                _save_camera_config(config)
                break

            elif key in (2490368, ord("w"), ord("W")):
                if key == last_nav_key and (now - last_nav_at) < KEY_REPEAT_INTERVAL:
                    continue
                last_nav_key = key
                last_nav_at = now
                selected_idx = (selected_idx - 1) % len(CONFIG_CONTROL_SPECS)
            elif key in (2621440, ord("s"), ord("S")):
                if key == last_nav_key and (now - last_nav_at) < KEY_REPEAT_INTERVAL:
                    continue
                last_nav_key = key
                last_nav_at = now
                selected_idx = (selected_idx + 1) % len(CONFIG_CONTROL_SPECS)
            elif key in (2424832, ord("a"), ord("A"), ord("-"), ord("j"), ord("J")):
                if key == last_nav_key and (now - last_nav_at) < KEY_REPEAT_INTERVAL:
                    continue
                last_nav_key = key
                last_nav_at = now
                _adjust_camera_control_value(control_state, selected_idx, -1)
            elif key in (2555904, ord("+"), ord("="), ord("l"), ord("L")):
                if key == last_nav_key and (now - last_nav_at) < KEY_REPEAT_INTERVAL:
                    continue
                last_nav_key = key
                last_nav_at = now
                _adjust_camera_control_value(control_state, selected_idx, 1)
            elif key in (ord("m"), ord("M")):
                last_nav_key = None
                control_state["auto_camera"] = 0 if int(control_state.get("auto_camera", 1)) == 1 else 1

            # RESET values to loaded config values
            elif key == ord("r"):
                last_nav_key = None
                control_state = _build_camera_control_state(config)

            # ⭐ QR PRESET (siêu quan trọng)
            elif key == ord("p"):
                last_nav_key = None
                control_state.update({
                    "auto_camera": 0,
                    "brightness": 68,
                    "contrast": 130,
                    "exposure": 7,
                    "gain": 6,
                    "focus": 42,
                    "sharpness": 74,
                    "saturation": 60,
                    "roi_width": 70,
                    "roi_height": 70,
                })
            elif key == ord("d"):
                last_nav_key = None
                config = _apply_default_camera_settings(cap, config)
                control_state = _build_camera_control_state(config)

                logger.info("Reset về default settings")
            elif key == -1:
                last_nav_key = None

    finally:
        _hard_release_camera(cap, (PREVIEW_WINDOW,))

    return config

def _apply_default_camera_settings(cap, config):
    # Không reset cứng resolution/fps ở màn preview để tránh đổi tỉ lệ khung đột ngột.

    # --- Config defaults ---
    default_config = _get_default_camera_config()
    config.update(default_config)

    auto_camera_enabled = bool(config.get("auto_camera", True))
    _set_camera_auto_mode(cap, auto_camera_enabled)

    # Áp dụng các thông số camera chính ngay trong phiên preview.
    if not auto_camera_enabled:
        cap.set(cv2.CAP_PROP_EXPOSURE,   config.get("exposure",   -1))
        cap.set(cv2.CAP_PROP_GAIN,       config.get("gain",       15))
        cap.set(cv2.CAP_PROP_FOCUS,      config.get("focus",      20))
        cap.set(cv2.CAP_PROP_SHARPNESS,  config.get("sharpness",  70))
        cap.set(cv2.CAP_PROP_SATURATION, config.get("saturation", 200))

    # ROI default (dynamic theo frame size)
    config["roi_scale"] = default_config["roi_scale"]
    config["roi_height_scale"] = default_config["roi_height_scale"]

    return config

def _gamma_correct_gray(gray: np.ndarray, gamma: float) -> np.ndarray:
    inv = 1.0 / max(0.1, gamma)
    lut = np.array([(i / 255.0) ** inv * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(gray, lut)


def _preprocess_for_qr(frame: np.ndarray, mean_luma: float | None = None) -> list[np.ndarray]:
    """
    Trả về danh sách ảnh đã xử lý theo thứ tự ưu tiên.
    Tự mở rộng pipeline khi ROI quá sáng/quá tối.
    """
    # Downscale 50% — pyzbar trên ảnh nhỏ nhanh hơn ~4x
    small = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_LINEAR)

    # Grayscale — giảm memory bandwidth, pyzbar không cần màu
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    if mean_luma is None:
        mean_luma = float(np.mean(gray))

    # CLAHE giúp cân bằng vùng tối/sáng cục bộ khi ánh sáng không đều.
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)

    # Làm nét nhẹ để tăng biên QR, tránh làm tăng noise quá mức.
    blur = cv2.GaussianBlur(eq, (0, 0), 1.2)
    sharpen = cv2.addWeighted(eq, 1.50, blur, -0.50, 0)

    # Base candidates
    _, otsu = cv2.threshold(sharpen, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        sharpen, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=41,
        C=8,
    )

    candidates: list[np.ndarray] = [otsu, adaptive, sharpen, eq, gray]

    # Tối: tăng sáng gamma tiered + CLAHE mạnh + denoise để phục hồi QR.
    if mean_luma < 85:
        # Tiered gamma: càng tối → càng khuếch đại mạnh hơn
        if mean_luma < 35:
            g = 0.22
        elif mean_luma < 55:
            g = 0.32
        elif mean_luma < 70:
            g = 0.42
        else:
            g = 0.52
        bright_gamma = _gamma_correct_gray(gray, g)

        # CLAHE mạnh trên ảnh đã brightened để tăng contrast cục bộ
        clahe_strong = cv2.createCLAHE(clipLimit=6.0, tileGridSize=(4, 4))
        bright_eq = clahe_strong.apply(bright_gamma)

        # Denoise nhẹ để giảm noise khuếch đại, giữ biên QR
        # bilateralFilter: nhanh hơn fastNlMeans ~10x, vẫn giữ biên QR tốt (thân thiện Pi 4)
        denoised = cv2.bilateralFilter(bright_eq, d=5, sigmaColor=40, sigmaSpace=40)

        # Nhiều biến thể ngưỡng với blockSize khác nhau
        _, otsu_d = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adp_d21 = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=21, C=5,
        )
        adp_d35 = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=35, C=7,
        )
        adp_d51 = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=51, C=9,
        )

        # Upscale 2x: pyzbar đọc tốt hơn trên ảnh lớn khi QR đặc trưng mờ
        candidates = [otsu_d, adp_d21, adp_d35, adp_d51, denoised, bright_eq] + candidates

    # Sáng/chói: nén highlight + thử bản đảo màu để vượt phản chiếu.
    if mean_luma > 180:
        dark_gamma = _gamma_correct_gray(eq, 1.55)
        _, otsu_bright = cv2.threshold(dark_gamma, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive_inv = cv2.adaptiveThreshold(
            dark_gamma, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            blockSize=35,
            C=7,
        )
        candidates.extend([otsu_bright, adaptive_inv, dark_gamma])

    return candidates


def _preprocess_for_qr_copy2(frame: np.ndarray) -> list[np.ndarray]:
    """Copy-2 pipeline: simple, fast, and stable for the kiosk scanner."""
    small = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=51,
        C=10,
    )

    return [otsu, adaptive, gray]


def _auto_adjust_exposure_for_roi(
    frame: np.ndarray,
    roi: tuple[int, int, int, int],
    state: dict[str, float],
) -> tuple[float, int, float]:
    """Tự điều chỉnh alpha/beta theo độ sáng ROI và trả thêm sharpness ROI."""
    state = _ensure_auto_camera_state(state)
    x, y, w, h = roi
    roi_frame = frame[y:y + h, x:x + w]
    if roi_frame.size == 0:
        return float(state["alpha"]), int(round(state["beta"])), 0.0

    sample = roi_frame
    sample_h, sample_w = sample.shape[:2]
    max_dim = max(sample_h, sample_w)
    if max_dim > 320:
        scale = 320.0 / float(max_dim)
        sample = cv2.resize(
            sample,
            (max(1, int(sample_w * scale)), max(1, int(sample_h * scale))),
            interpolation=cv2.INTER_AREA,
        )

    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    mean_luma = float(np.mean(gray))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    local_contrast = float(np.std(gray))
    shadow_ratio = float(np.mean(gray < 72))
    highlight_ratio = float(np.mean(gray > 215))

    # Đẩy target sáng hơn một chút để preview bớt tối.
    target_luma = AUTO_CAMERA_TARGET_LUMA
    err = target_luma - mean_luma
    if abs(err) < AUTO_CAMERA_PREVIEW_LUMA_DEADBAND:
        err = 0.0

    next_beta = state["beta"] + (0.18 * err) + (shadow_ratio * 18.0) - (highlight_ratio * 24.0)
    next_beta = float(np.clip(next_beta, -30.0, 96.0))

    if mean_luma < 50:
        desired_alpha = 1.55
    elif mean_luma < 75:
        desired_alpha = 1.38
    elif mean_luma < 100:
        desired_alpha = 1.24
    elif mean_luma > 210:
        desired_alpha = 0.88
    elif mean_luma > 185:
        desired_alpha = 0.95
    else:
        desired_alpha = 1.08

    if local_contrast < 40.0:
        desired_alpha += 0.06
    if sharpness < AUTO_CAMERA_SHARPNESS_LOW:
        desired_alpha += 0.05
    if highlight_ratio > AUTO_CAMERA_HIGHLIGHT_RATIO_HIGH:
        desired_alpha = min(desired_alpha, 1.02)

    # Smoothing để tránh nhấp nháy mạnh khi ánh sáng dao động.
    prev_alpha = float(state["alpha"])
    prev_beta = float(state["beta"])
    smoothed_alpha = (prev_alpha * 0.86) + (desired_alpha * 0.14)
    smoothed_beta = (prev_beta * 0.78) + (next_beta * 0.22)
    state["alpha"] = float(np.clip(
        smoothed_alpha,
        max(0.88, prev_alpha - AUTO_CAMERA_PREVIEW_ALPHA_MAX_STEP),
        min(1.65, prev_alpha + AUTO_CAMERA_PREVIEW_ALPHA_MAX_STEP),
    ))
    state["beta"] = float(np.clip(
        smoothed_beta,
        max(-30.0, prev_beta - AUTO_CAMERA_PREVIEW_BETA_MAX_STEP),
        min(96.0, prev_beta + AUTO_CAMERA_PREVIEW_BETA_MAX_STEP),
    ))
    state["mean_luma"] = mean_luma
    state["sharpness"] = sharpness
    state["shadow_ratio"] = shadow_ratio
    state["highlight_ratio"] = highlight_ratio
    state["local_contrast"] = local_contrast

    return float(state["alpha"]), int(round(state["beta"])), sharpness


def _kick_autofocus_if_blurry(cap, state: dict[str, float], sharpness: float) -> None:
    """Kích hoạt lại autofocus theo chu kỳ khi ROI mờ kéo dài."""
    state = _ensure_auto_camera_state(state)
    now = time.monotonic()
    blur_threshold = AUTO_CAMERA_SHARPNESS_LOW
    recover_threshold = AUTO_CAMERA_SHARPNESS_RECOVER
    mean_luma = float(state.get("mean_luma", AUTO_CAMERA_TARGET_LUMA))
    local_contrast = float(state.get("local_contrast", 0.0))

    if mean_luma < 58.0 or local_contrast < AUTO_CAMERA_MIN_LOCAL_CONTRAST_FOR_AF:
        state["blur_count"] = max(0.0, state["blur_count"] - 0.8)
        return

    if sharpness < blur_threshold:
        state["blur_count"] += 1.0 if mean_luma >= 72.0 else 0.55
    elif sharpness >= recover_threshold:
        state["blur_count"] = 0.0
    else:
        state["blur_count"] = max(0.0, state["blur_count"] - 0.35)

    if state["blur_count"] < 10.0:
        return
    if (now - state["last_af_kick"]) < AUTO_CAMERA_REFOCUS_MIN_SEC:
        return

    state["last_af_kick"] = now
    state["blur_count"] = 0.0
    try:
        # Pulse autofocus để camera refocus lại tâm ảnh.
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
    except Exception:
        pass


def _decode_qr(images: list[np.ndarray]) -> str | None:
    """Thử decode lần lượt các ảnh preprocessed, dừng ngay khi có kết quả."""
    for img in images:
        codes = pyzbar.decode(img, symbols=[ZBarSymbol.QRCODE])
        if codes:
            return codes[0].data.decode("utf-8")
    return None


def _is_likely_qr_payload(payload: str) -> bool:
    """Kiểm tra sơ bộ payload QR có khả năng là base64 mã hóa AES-GCM."""
    if not isinstance(payload, str):
        return False
    payload = payload.strip()
    if payload.startswith("v1:"):
        payload = payload[3:]
    if len(payload) < 16 or len(payload) % 4 != 0:
        return False
    allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
    return all(ch in allowed_chars for ch in payload)


def _get_font(size: int):
    """Load font hỗ trợ tiếng Việt, fallback về default nếu không có."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_text_pil(img: np.ndarray, text: str, xy: tuple, size=36, color=(0, 200, 0)) -> np.ndarray:
    """Vẽ text Unicode lên frame bằng Pillow."""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    draw.text(xy, text, font=_get_font(size), fill=color)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def _draw_text_centered_pil(img: np.ndarray, text: str, y: int, size=28, color=(0, 200, 0)) -> np.ndarray:
    """Vẽ text Unicode canh giữa ngang trên frame bằng Pillow."""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    font = _get_font(size)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    x = max(0, (img.shape[1] - text_w) // 2)
    draw.text((x, y), text, font=font, fill=color)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def _draw_checkin_info_pil(
    img: np.ndarray,
    checkin_time: str,
    queue_number: str,
    y: int,
    size: int = 24,
    color_time=(28, 180, 50),
    color_label=(28, 180, 50),
    color_number=(28, 180, 50),
    line_gap: int = 14,
) -> np.ndarray:
    """Vẽ thông tin đã check in: thời gian và số thứ tự, trình bày đẹp."""
    checkin_time = str(checkin_time or "--:--").strip()
    queue_number = str(queue_number or "---").strip()

    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    font = _get_font(size)
    # Dòng trên: "Bạn đã check in vào lúc hh:mm"
    time_text = f"Bạn đã check in vào lúc {checkin_time}"
    bbox_time = draw.textbbox((0, 0), time_text, font=font)
    text_w_time = bbox_time[2] - bbox_time[0]
    text_h_time = bbox_time[3] - bbox_time[1]
    x_time = max(0, (img.shape[1] - text_w_time) // 2)
    draw.text((x_time, y), time_text, font=font, fill=color_time)
    # Dòng dưới: "Số thứ tự: xx" (label và số khác màu)
    label = "Số thứ tự: "
    number = queue_number
    label_font = font
    number_font = font
    bbox_label = draw.textbbox((0, 0), label, font=label_font)
    bbox_number = draw.textbbox((0, 0), number, font=number_font)
    text_w_label = bbox_label[2] - bbox_label[0]
    text_w_number = bbox_number[2] - bbox_number[0]
    total_w = text_w_label + text_w_number
    x_label = max(0, (img.shape[1] - total_w) // 2)
    y2 = y + text_h_time + line_gap
    draw.text((x_label, y2), label, font=label_font, fill=color_label)
    draw.text((x_label + text_w_label, y2), number, font=number_font, fill=color_number)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def _is_arrived_checkin_message(message: str) -> bool:
    lower = str(message or "").strip().lower()
    return (
        "bạn đã check in vào lúc" in lower
        or "bạn đã check-in lúc" in lower
        or "ban da check in vao luc" in lower
        or "ban da check-in luc" in lower
    )


def _extract_checkin_info(message: str) -> tuple[str, str]:
    raw = str(message or "").strip()
    lower = raw.lower()

    time_match = re.search(r"([0-2]?\d:[0-5]\d)", lower)
    checkin_time = time_match.group(1) if time_match else "--:--"

    queue_number = "---"
    for line in raw.splitlines():
        normalized = line.lower().strip()
        if ("số thứ tự" in normalized) or ("so thu tu" in normalized) or ("stt" in normalized):
            queue_number = line.split(":", 1)[1].strip() if ":" in line else line.strip()
            break

    return checkin_time, queue_number


def _wrap_result_text_lines(text: str, width: int = 40) -> str:
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        cleaned = raw.strip()
        if not cleaned:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(cleaned, width=width, break_long_words=True, break_on_hyphens=False))
    return "\n".join(lines)


def _render_result_screen(
    width: int,
    height: int,
    kind: str,
    primary_text: str,
    secondary_text: str = "",
) -> np.ndarray:
    """Render unified result screen with consistent icon/text layout (scaled to resolution)."""
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)
    # Scale factor relative to 1080p baseline
    base_h = 1080
    sf = height / base_h
    cx = width // 2
    icon_cy = int(height * 0.38)
    title_y = int(height * 0.10)
    text_y = int(height * 0.56)
    icon_radius = max(40, int(90 * sf))
    title_size = max(28, int(52 * sf))
    text_size = max(26, int(44 * sf))
    line_gap = max(10, int(18 * sf))

    title_by_kind = {
        "success": "Quét mã QR thành công",
        "already_checked_in": "Thông tin check-in",
        "invalid_qr": "Mã QR không hợp lệ",
        "cancelled": "Mã QR đã hết hạn hoặc bị hủy",
        "error": "Không thể xử lý mã QR",
    }
    title = title_by_kind.get(kind, "Kết quả quét QR")
    title_color = {
        "success": (28, 102, 50),
        "already_checked_in": (28, 180, 50),
        "invalid_qr": (180, 60, 0),
        "cancelled": (120, 20, 20),
        "error": (120, 20, 20),
    }.get(kind, (40, 40, 40))

    canvas = _draw_text_centered_pil(canvas, title, title_y, size=title_size, color=title_color)

    if kind == "invalid_qr":
        tri_h = int(icon_radius * 1.6)
        tri_w = int(icon_radius * 1.8)
        tri_pts = np.array(
            [
                [cx, icon_cy - tri_h // 2],
                [cx - tri_w // 2, icon_cy + tri_h // 2],
                [cx + tri_w // 2, icon_cy + tri_h // 2],
            ],
            np.int32,
        )
        cv2.fillPoly(canvas, [tri_pts], (0, 140, 255))
        cv2.polylines(canvas, [tri_pts], isClosed=True, color=(0, 100, 210), thickness=3)
        cv2.putText(
            canvas,
            "!",
            (cx - int(8 * sf), icon_cy + int(22 * sf)),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5 * sf,
            (255, 255, 255),
            max(3, int(4 * sf)),
            cv2.LINE_AA,
        )
    else:
    # ================= CANCELLED =================
        if kind == "cancelled":
            fill_color = (0, 0, 255)
            cross_color = (255, 255, 255)

            cv2.circle(canvas, (cx, icon_cy), icon_radius,
                    fill_color, -1, cv2.LINE_AA)

            offset = int(18 * sf)
            thickness = int(7 * sf)

            cv2.line(canvas,
                    (cx - offset, icon_cy - offset),
                    (cx + offset, icon_cy + offset),
                    cross_color, thickness, cv2.LINE_AA)

            cv2.line(canvas,
                    (cx + offset, icon_cy - offset),
                    (cx - offset, icon_cy + offset),
                    cross_color, thickness, cv2.LINE_AA)

        # ================= SUCCESS / ERROR =================
        else:
            fill_color = {
                "success": (47, 184, 93),
                "already_checked_in": (28, 180, 50),
                "error": (232, 93, 4),
            }.get(kind, (47, 184, 93))

            stroke_color = {
                "success": (21, 128, 61),
                "already_checked_in": (28, 180, 50),
                "error": (150, 63, 0),
            }.get(kind, (21, 128, 61))

            cv2.circle(canvas, (cx, icon_cy), icon_radius,
                    fill_color, -1, cv2.LINE_AA)
            cv2.circle(canvas, (cx, icon_cy), icon_radius,
                    stroke_color, 3, cv2.LINE_AA)

            if kind in {"success", "already_checked_in"}:
                cv2.line(
                    canvas,
                    (cx - int(22 * sf), icon_cy + int(2 * sf)),
                    (cx - int(8 * sf), icon_cy + int(18 * sf)),
                    (255, 255, 255),
                    max(5, int(7 * sf)),
                    cv2.LINE_AA,
                )
                cv2.line(
                    canvas,
                    (cx - int(8 * sf), icon_cy + int(18 * sf)),
                    (cx + int(26 * sf), icon_cy - int(14 * sf)),
                    (255, 255, 255),
                    max(5, int(7 * sf)),
                    cv2.LINE_AA,
                )

    merged_text = str(primary_text or "").strip()
    if secondary_text and str(secondary_text).strip():
        merged_text = f"{merged_text}\n{str(secondary_text).strip()}" if merged_text else str(secondary_text).strip()
    merged_text = _wrap_result_text_lines(merged_text, width=40)
    body_color = {
        "success": (22, 101, 52),
        "already_checked_in": (28, 180, 50),
        "invalid_qr": (120, 80, 0),
        "cancelled": (120, 20, 20),
        "error": (120, 20, 20),
    }.get(kind, (40, 40, 40))
    canvas = _draw_multiline_centered_pil(
        canvas,
        merged_text,
        text_y,
        size=text_size,
        color=body_color,
        line_gap=line_gap,
    )
    return canvas


def _render_success_screen(
    width: int,
    height: int,
    greeting: str,
    detail: str = "",
) -> np.ndarray:
    """Backward-compatible wrapper for unified result renderer."""
    return _render_result_screen(width, height, "success", greeting, detail)


def _draw_scan_frame(frame: np.ndarray, roi: tuple) -> np.ndarray:
    """
    Chỉ hiển thị camera trong ROI, ngoài ROI là nền trắng, vẽ viền xanh quanh ROI.
    """
    x, y, fw, fh = roi
    H, W = frame.shape[:2]
    out = np.full((H, W, 3), 255, dtype=np.uint8)
    # Copy ROI từ frame vào out
    out[y:y+fh, x:x+fw] = frame[y:y+fh, x:x+fw]
    # Vẽ viền xanh quanh ROI
    color = (0, 220, 0)
    t = 3
    cv2.rectangle(out, (x, y), (x+fw-1, y+fh-1), color, t)
    return out


def _resize_fill(frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """Resize frame to fill target size (stretch, no letterbox)."""
    if target_w <= 0 or target_h <= 0:
        return frame
    h, w = frame.shape[:2]
    if h <= 0 or w <= 0:
        return frame

    interpolation = cv2.INTER_LINEAR if max(target_w / w, target_h / h) >= 1.0 else cv2.INTER_AREA
    return cv2.resize(frame, (target_w, target_h), interpolation=interpolation)


DISPLAY_ZOOM_OUT_FACTOR = 0.85


def _apply_display_zoom_out(frame: np.ndarray, zoom_factor: float = DISPLAY_ZOOM_OUT_FACTOR) -> np.ndarray:
    """Shrink the rendered scanner view inside its own canvas for a zoomed-out display."""
    h, w = frame.shape[:2]
    if h <= 0 or w <= 0:
        return frame

    zoom_factor = float(np.clip(zoom_factor, 0.1, 1.0))
    if zoom_factor >= 0.999:
        return frame

    resized_w = max(1, int(round(w * zoom_factor)))
    resized_h = max(1, int(round(h * zoom_factor)))
    interpolation = cv2.INTER_LINEAR if zoom_factor >= 1.0 else cv2.INTER_AREA
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=interpolation)

    canvas = np.zeros((h, w, 3), dtype=frame.dtype)
    y_off = max(0, (h - resized_h) // 2)
    x_off = max(0, (w - resized_w) // 2)
    canvas[y_off:y_off + resized_h, x_off:x_off + resized_w] = resized
    return canvas


def _load_keys() -> list[bytes]:
    load_dotenv()
    primary_key_b64 = (os.getenv("AES_GCM_KEY_B64") or "").strip()
    alt_keys_raw = (os.getenv("AES_GCM_ALT_KEYS_B64") or "").strip()

    raw_values: list[str] = []
    if primary_key_b64:
        raw_values.append(primary_key_b64)
    if alt_keys_raw:
        raw_values.extend(item.strip() for item in alt_keys_raw.split(",") if item.strip())

    if not raw_values:
        raise RuntimeError("Missing AES_GCM_KEY_B64 in environment")

    keys: list[bytes] = []
    for value in raw_values:
        try:
            keys.append(base64.b64decode(value))
        except Exception as exc:
            raise RuntimeError(f"Invalid AES key format: {exc}") from exc
    return keys


def _decode_payload(payload: str) -> bytes:
    if payload.startswith("v1:"):
        payload = payload[3:]
    return base64.b64decode(payload)


def decrypt_patient_id(payload: str, keys: list[bytes]) -> str:
    raw = _decode_payload(payload)
    if len(raw) <= 12:
        raise ValueError("Payload quá ngắn để giải mã")

    nonce = raw[:12]
    ct_tag = raw[12:]
    errors: list[str] = []
    for key in keys:
        try:
            aesgcm = AESGCM(key)
            pt = aesgcm.decrypt(nonce, ct_tag, None)
            return pt.decode("utf-8")
        except Exception as exc:
            detail = str(exc).strip()
            errors.append(detail or type(exc).__name__)

    raise ValueError(
        f"Không giải mã được với {len(keys)} khóa đã cấu hình: {'; '.join(errors)}"
    )


def _extract_patient_name(data: Any) -> str:
    """Return a display name from a patient payload using common field names."""
    if not isinstance(data, dict):
        return ""

    candidate_keys = (
        "name",
        "full_name",
        "fullName",
        "patient_name",
        "patientName",
        "ho_ten",
        "hoTen",
        "ten",
        "displayName",
    )
    for key in candidate_keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_patient(data: dict) -> dict:
    """Convert firebase-style dicts into normalized patient data."""
    normalized = dict(data)
    if "appointments" in normalized and isinstance(normalized["appointments"], dict):
        appts = []
        for appt_id, appt in normalized["appointments"].items():
            if isinstance(appt, dict):
                entry = dict(appt)
                entry["id"] = appt_id
                appts.append(entry)
            else:
                appts.append({"id": appt_id, "value": appt})
        normalized["appointments"] = appts
    return normalized


_ALREADY_ARRIVED_SENTINEL = "__da_den__"


def _format_hhmm(value: Any) -> str:
    """Convert stored timestamp-like values to HH:MM for kiosk messages."""
    try:
        if isinstance(value, str) and value.strip().isdigit():
            ts = int(value.strip())
            return time.strftime("%H:%M", time.localtime(ts))
        if isinstance(value, (int, float)):
            return time.strftime("%H:%M", time.localtime(int(value)))
    except Exception:
        pass
    return "--:--"


def _normalize_appointment_date(date_raw: str) -> str:
    """Convert various date formats to YYYY-MM-DD. Returns empty string if invalid."""
    from datetime import datetime as _dt
    text = str(date_raw or "").strip()
    if not text:
        return ""
    
    # Strip time component if present (ISO datetime)
    if "T" in text:
        text = text.split("T", 1)[0]
    
    # Try to parse various date formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return _dt.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _process_payload_and_update(
    payload: str,
    patients_path: str = "patients",
    appointments_path: str = "appointment_new",
) -> tuple[str, str]:
    """Decrypt payload (appointment ID), fetch appointment → patient, update status.

    Returns (message, patient_name).
    If the appointment is already marked as arrived, returns (_ALREADY_ARRIVED_SENTINEL, "")
    so the caller can silently skip without showing anything on screen.
    """
    try:
        keys = _load_keys()
    except Exception as exc:  # pragma: no cover - environment errors
        return f"Lỗi khóa: {exc}", ""

    try:
        appointment_id = decrypt_patient_id(payload, keys)
    except Exception as exc:
        return f"Lỗi giải mã QR: {exc}", ""

    # Fetch appointment record by ID
    appt = get_appointment(appointment_id, base_path=appointments_path)
    if not appt or not isinstance(appt, dict):
        return f"Không tìm thấy lịch khám: {appointment_id}", ""

    appt_status = str(appt.get("status", "")).strip().lower()

    # If visit completed — show final thank-you message.
    completed_statuses = {
        "done", "completed", "finished", "đã khám", "da kham", "hoàn tất", "hoan tat",
    }
    if appt_status in completed_statuses:
        return "Lần khám bệnh đã hoàn tất ! Cảm ơn quý khách đã tin tưởng và sử dụng dịch vụ của chúng tôi", ""

    # If already arrived — safe re-scan: show original check-in time + queue number.
    arrived_statuses = {"đã đến", "da den", "arrived", "checked_in", "checked in"}
    if appt_status in arrived_statuses:
        checkin_hhmm = _format_hhmm(
            appt.get("checkedInAt")
            or appt.get("arrivedAt")
            or appt.get("checkinAt")
        )
        queue_number = (
            appt.get("queueNumber")
            or appt.get("queue_number")
            or appt.get("stt")
            or "---"
        )
        return f"Bạn đã check in vào lúc: {checkin_hhmm}\nSố thứ tự: {queue_number}", ""

    cancelled_statuses = {"cancelled", "canceled", "da huy", "đã hủy"}
    if appt_status in cancelled_statuses:
        return "Lịch của bạn đã hủy vui lòng kiểm tra lại", ""

    no_show_statuses = {"no_show", "no-show", "no show", "qua han", "quá hạn", "expired"}
    if appt_status in no_show_statuses:
        return "Lịch của quý khách đã quá hẹn vui lòng đặt lịch mới", ""

    # === Date validation: prevent check-in before/after the appointment date ===
    appt_date_raw = str(
        appt.get("date")
        or appt.get("appointmentDate")
        or appt.get("queueDate")
        or ""
    ).strip()

    if appt_date_raw:
        appt_date_iso = _normalize_appointment_date(appt_date_raw)
        today_iso = time.strftime("%Y-%m-%d", time.localtime())

        if appt_date_iso and appt_date_iso > today_iso:
            # Check-in trước ngày hẹn
            try:
                from datetime import datetime as _dt
                display_date = _dt.strptime(appt_date_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
            except Exception:
                display_date = appt_date_iso
            return (
                f"Chưa đến ngày khám\nLịch hẹn của bạn vào ngày {display_date}\nVui lòng quay lại đúng ngày để check-in",
                ""
            )

        if appt_date_iso and appt_date_iso < today_iso:
            # Check-in sau ngày hẹn (lịch quá hạn)
            return "Lịch khám đã quá hạn\nVui lòng đặt lịch mới để được khám", ""

    # Resolve patient from appointment
    patient_id = (
        appt.get("patientID")
        or appt.get("patient_id")
        or appt.get("patientId")
    )
    if not patient_id:
        return "Lịch khám không có thông tin bệnh nhân", ""

    data = get_patient(patient_id, base_path=patients_path)
    if not data:
        return f"Không tìm thấy thông tin bệnh nhân: {patient_id}", ""

    patient_name = _extract_patient_name(data)

    # Resolve doctor ID from appointment
    doctor_id = (
        appt.get("doctorID")
        or appt.get("doctorId")
        or appt.get("doctor_id")
    )

    # Add patient to doctor queue and update queue_meta (only first check-in)
    queue_number: int | str = "---"
    if doctor_id:
        queue_number = add_patient_to_queue(
            appointment_id=appointment_id,
            patient_id=patient_id,
            patient_name=patient_name,
            doctor_id=doctor_id,
        )
        if queue_number == -1:
            logger.warning("Không thể thêm vào hàng đợi cho bác sĩ %s", doctor_id)
            queue_number = "---"
    else:
        logger.warning("Lịch khám %s không có doctorID, bỏ qua tạo queue", appointment_id)

    # Persist arrival metadata on appointment for safe re-scan.
    checkin_ts = int(time.time())
    queue_date = time.strftime("%Y-%m-%d", time.localtime(checkin_ts))
    updates = {
        "status": "arrived",
        "checkedInAt": checkin_ts,
        "queueDate": queue_date,
        "queueNumber": queue_number,
    }

    # Prefer direct write to appointment_new/{doctor_id}/{date}/{appointment_id}.
    direct_ok = False
    appt_date_key = str(
        appt.get("date")
        or appt.get("appointmentDate")
        or appt.get("queueDate")
        or ""
    ).strip()
    if "T" in appt_date_key:
        appt_date_key = appt_date_key.split("T", 1)[0]

    if appointments_path == "appointment_new" and doctor_id and appt_date_key:
        try:
            get_db_ref(f"{appointments_path}/{doctor_id}/{appt_date_key}/{appointment_id}").update(updates)
            direct_ok = True
        except Exception:
            direct_ok = False

    ok = direct_ok or update_global_appointment_fields(
        appointment_id,
        updates,
        base_path=appointments_path,
    )
    if not ok:
        return "Không thể cập nhật trạng thái: không tìm thấy lịch hẹn trong node đã chọn", patient_name

    # First-time check-in (scheduled -> arrived): let controller show welcome message only.
    return "", patient_name


def _draw_step_ui(img, step: int, W, H):
    steps = ["Đưa QR vào khung", "Giữ ổn định camera", "Đang xử lý dữ liệu"]

    base_y = 40

    for i, text in enumerate(steps, start=1):
        color = (0, 255, 0) if i <= step else (150, 150, 150)

        cv2.putText(
            img,
            f"{i}. {text}",
            (20, base_y + (i - 1) * 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2
        )

    return img
def _open_selected_camera(camera_index):
    """
    Mở camera theo device path hoặc index.
    Hỗ trợ:
        0
        "0"
        "/dev/video0"
    """

    # Đảm bảo camera_index đúng kiểu, log rõ ràng
    print(f"[DEBUG] _open_selected_camera: camera_index={camera_index!r}")
    if isinstance(camera_index, str):
        raw = camera_index.strip()
        if raw.startswith("/dev/video"):
            target = raw
        elif raw.isdigit():
            target = int(raw)
        elif not raw:
            target = 0
        else:
            print(f"[ERROR] Chỉ số camera không hợp lệ: {camera_index}")
            raise RuntimeError(f"Chỉ số camera không hợp lệ: {camera_index}")
    else:
        try:
            target = int(camera_index)
        except (ValueError, TypeError):
            print(f"[ERROR] Không convert được camera_index: {camera_index}")
            target = 0

    last_err = None
    for _ in range(CAMERA_OPEN_ATTEMPTS):
        with camera_lock:
            cap = _open_camera(target)
        if cap is not None and cap.isOpened():
            return cap
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
        last_err = f"Không mở được camera: {camera_index}"
        for window_name in ("QR Scanner", "Camera Config"):
            try:
                cv2.destroyWindow(window_name)
            except Exception:
                pass
        try:
            cv2.waitKey(1)
        except Exception:
            pass
        time.sleep(CAMERA_OPEN_RETRY_SEC)

    raise RuntimeError(last_err or f"Không mở được camera: {camera_index}")


def _release_capture_only(cap) -> None:
    try:
        if cap is not None:
            cap.release()
    except Exception:
        pass


def _apply_camera_runtime_settings(
    cap,
    config: dict,
    auto_camera_enabled: bool,
    use_windows_native_defaults: bool,
    *,
    default_width: int,
    default_height: int,
    default_fps: int,
    prefer_mjpg: bool,
) -> None:
    target_width = int(config.get("camera_width", default_width))
    target_height = int(config.get("camera_height", default_height))
    target_fps = int(config.get("camera_fps", default_fps))

    if not use_windows_native_defaults:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_height)
        cap.set(cv2.CAP_PROP_FPS, target_fps)
        if prefer_mjpg:
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            except Exception:
                pass
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
        _set_camera_auto_mode(cap, auto_camera_enabled)

    if not auto_camera_enabled:
        cap.set(cv2.CAP_PROP_BRIGHTNESS, config.get("brightness", 80))
        cap.set(cv2.CAP_PROP_EXPOSURE, config.get("exposure", -1))
        cap.set(cv2.CAP_PROP_GAIN, config.get("gain", 15))
        cap.set(cv2.CAP_PROP_SHARPNESS, config.get("sharpness", 70))
        cap.set(cv2.CAP_PROP_SATURATION, config.get("saturation", 200))
        cap.set(cv2.CAP_PROP_FOCUS, config.get("focus", 20))
        if config.get("contrast") is not None:
            cap.set(cv2.CAP_PROP_CONTRAST, config.get("contrast", 1.15))


def _read_first_frame_with_retries(
    cap,
    attempts: int = CAMERA_FIRST_FRAME_ATTEMPTS,
    retry_sleep_sec: float = CAMERA_FIRST_FRAME_RETRY_SEC,
) -> tuple[bool, np.ndarray | None]:
    last_frame = None
    for _ in range(max(1, int(attempts))):
        ok, frame = cap.read()
        if ok and frame is not None and getattr(frame, "size", 0) > 0:
            return True, frame
        last_frame = frame
        time.sleep(retry_sleep_sec)
    return False, last_frame


def _open_and_warmup_camera(
    camera_index: int | str,
    config: dict,
    auto_camera_enabled: bool,
    use_windows_native_defaults: bool,
    *,
    default_width: int,
    default_height: int,
    default_fps: int,
    prefer_mjpg: bool = True,
) -> tuple[Any, np.ndarray]:
    cap = _open_selected_camera(camera_index)
    _apply_camera_runtime_settings(
        cap,
        config,
        auto_camera_enabled,
        use_windows_native_defaults,
        default_width=default_width,
        default_height=default_height,
        default_fps=default_fps,
        prefer_mjpg=prefer_mjpg,
    )

    ok, first_frame = _read_first_frame_with_retries(cap)
    if ok:
        return cap, first_frame if first_frame is not None else np.zeros((1, 1, 3), dtype=np.uint8)

    if prefer_mjpg:
        logger.warning(
            "Không đọc được frame đầu tiên với cấu hình MJPG/buffer tối ưu; thử fallback tương thích."
        )
        _release_capture_only(cap)
        cap = _open_selected_camera(camera_index)
        _apply_camera_runtime_settings(
            cap,
            config,
            auto_camera_enabled,
            use_windows_native_defaults,
            default_width=default_width,
            default_height=default_height,
            default_fps=default_fps,
            prefer_mjpg=False,
        )
        ok, first_frame = _read_first_frame_with_retries(cap)
        if ok:
            logger.info("Fallback camera thành công (không ép MJPG/buffer).")
            return cap, first_frame if first_frame is not None else np.zeros((1, 1, 3), dtype=np.uint8)

    if not use_windows_native_defaults:
        logger.warning(
            "Fallback tương thích vẫn chưa đọc được frame; thử profile an toàn 640x480@15."
        )
        _release_capture_only(cap)
        cap = _open_selected_camera(camera_index)
        safe_config = dict(config)
        safe_config["camera_width"] = 640
        safe_config["camera_height"] = 480
        safe_config["camera_fps"] = 15
        _apply_camera_runtime_settings(
            cap,
            safe_config,
            auto_camera_enabled,
            use_windows_native_defaults,
            default_width=640,
            default_height=480,
            default_fps=15,
            prefer_mjpg=False,
        )
        ok, first_frame = _read_first_frame_with_retries(cap)
        if ok:
            logger.info("Fallback profile an toàn thành công.")
            return cap, first_frame if first_frame is not None else np.zeros((1, 1, 3), dtype=np.uint8)

    _release_capture_only(cap)
    raise RuntimeError("Không đọc được frame đầu tiên từ camera")

def _legacy_scan_from_camera(
    camera_index: int | str | None = None,
    patients_path: str = "patients",
    appointments_path: str = "appointment_new",
    config: dict | None = None,
) -> str | None:
    """Copy-2 style scanner loop adapted for IoT-backup business logic."""
    _LEGACY_SCAN_STOP_EVENT.clear()
    if config is None:
        config = _load_camera_config()
    if camera_index is None:
        camera_index = config.get("camera_index", 0)
    auto_camera_enabled = bool(config.get("auto_camera", True))
    use_windows_native_defaults = _use_windows_native_camera_defaults(auto_camera_enabled)
    cap, first_frame = _open_and_warmup_camera(
        camera_index=camera_index,
        config=config,
        auto_camera_enabled=auto_camera_enabled,
        use_windows_native_defaults=use_windows_native_defaults,
        default_width=1280,
        default_height=720,
        default_fps=30,
        prefer_mjpg=True,
    )

    H, W = first_frame.shape[:2]
    cv2.namedWindow("QR Scanner", cv2.WINDOW_NORMAL | cv2.WINDOW_FREERATIO)
    try:
        cv2.setWindowProperty("QR Scanner", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    except Exception:
        pass
    try:
        cv2.setWindowProperty("QR Scanner", cv2.WND_PROP_ASPECT_RATIO, cv2.WINDOW_FREERATIO)
    except Exception:
        pass
    try:
        cv2.moveWindow("QR Scanner", 0, 0)
    except Exception:
        pass
    screen_w, screen_h = W, H

    roi_scale = config.get("roi_scale", 0.7)
    roi_height_scale = config.get("roi_height_scale", roi_scale)
    roi_w = int(W * roi_scale)
    roi_h = int(H * roi_height_scale)
    roi_x = (W - roi_w) // 2
    roi_y = (H - roi_h) // 2
    roi = (roi_x, roi_y, roi_w, roi_h)

    result_data: str | None = None
    scan_success = False
    success_frame_count = 0
    last_message = ""
    patient_name = ""
    scan_result_kind = "success"
    custom_cancelled_msg = config.get(
        "custom_message",
        "Mã lịch hẹn đã bị hủy hoặc quá hạn vui lòng kiểm tra lại",
    )

    if auto_camera_enabled:
        contrast_alpha = 1.0
        brightness_beta = 0
    else:
        contrast_alpha = float(config.get("contrast", 1.15))
        brightness_beta = int(config.get("brightness", 80)) - 50

    decode_interval = 3
    frame_count = 0

    try:
        while True:
            if _LEGACY_SCAN_STOP_EVENT.is_set():
                break

            ok, frame = cap.read()
            if not ok:
                break

            frame_count += 1
            adjusted_frame = cv2.convertScaleAbs(
                frame,
                alpha=contrast_alpha,
                beta=brightness_beta,
            )

            if not scan_success and frame_count % decode_interval == 0:
                roi_frame = adjusted_frame[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
                data = _decode_qr(_preprocess_for_qr_copy2(roi_frame))

                if data and not _is_likely_qr_payload(data):
                    result_data = None
                    patient_name = ""
                    last_message = "Mã QR không hợp lệ. Vui lòng thử lại."
                    scan_result_kind = "invalid_qr"
                    logger.warning("QR payload không hợp lệ: %s", data[:48])
                    scan_success = True
                    success_frame_count = 0
                elif data and _is_likely_qr_payload(data):
                    result_data = data
                    last_message, patient_name = _process_payload_and_update(
                        data,
                        patients_path=patients_path,
                        appointments_path=appointments_path,
                    )
                    lower_decode = (last_message or "").lower()
                    if ("giai ma qr" in lower_decode) or ("giải mã qr" in lower_decode):
                        result_data = None
                        patient_name = ""
                        last_message = "Mã QR không hợp lệ. Vui lòng thử lại."
                        scan_result_kind = "invalid_qr"
                        logger.warning("Lỗi giải mã QR")
                        scan_success = True
                        success_frame_count = 0
                        continue
                    if last_message == _ALREADY_ARRIVED_SENTINEL or (last_message and last_message.startswith("Lỗi giải mã QR")):
                        result_data = None
                        last_message = ""
                    else:
                        lower = last_message.lower() if last_message else ""
                        if "chưa đến ngày khám" in lower or "đã quá hạn" in lower or "đã quá hẹn" in lower or "đã hủy" in lower or "hủy" in lower or "quá hạn" in lower:
                            scan_result_kind = "cancelled"
                        elif "mã qr không hợp lệ" in lower or "lỗi" in lower or "không" in lower or "fail" in lower:
                            scan_result_kind = "error"
                        elif _is_arrived_checkin_message(last_message):
                            scan_result_kind = "already_checked_in"
                        else:
                            scan_result_kind = "success"
                        logger.info(last_message)
                        scan_success = True
                        success_frame_count = 0

            if scan_success:
                # Render result screens at high resolution for crisp text
                _rw = max(W, 1920)
                _rh = max(H, 1080)
                display = np.full((_rh, _rw, 3), 255, dtype=np.uint8)

                if scan_result_kind == "already_checked_in":
                    try:
                        checkin_time, queue_number = _extract_checkin_info(last_message)
                    except Exception:
                        checkin_time, queue_number = "--:--", "---"
                    display = _render_result_screen(
                        _rw,
                        _rh,
                        "already_checked_in",
                        f"Bạn đã check in vào lúc {checkin_time}",
                        f"Số thứ tự: {queue_number}",
                    )
                elif scan_result_kind == "invalid_qr":
                    display = _render_result_screen(
                        _rw,
                        _rh,
                        "invalid_qr",
                        "Lỗi khi quét mã QR",
                        last_message,
                    )
                elif scan_result_kind == "cancelled":
                    # Giao diện quét thành công nhưng bị cancelled: logo đỏ, text "Lịch hẹn đã bị hủy hoặc quá hạn!" nổi bật, không hiển thị icon check xanh.
                    display = _render_result_screen(
                        _rw,
                        _rh,
                        "cancelled",
                        "",
                        custom_cancelled_msg,
                    )
                elif scan_result_kind == "error":
                    display = _render_result_screen(
                        _rw,
                        _rh,
                        "error",
                        last_message or "Có lỗi xảy ra, vui lòng thử lại.",
                    )
                else:
                    greeting_success = (
                        f"Chào mừng quý khách {patient_name} đã đến phòng khám"
                        if patient_name
                        else "Chào mừng quý khách đã đến phòng khám"
                    )

                    display = _render_success_screen(
                        _rw,
                        _rh,
                        greeting=greeting_success,
                        detail=last_message if last_message else None,
                    )

                success_frame_count += 1
                if success_frame_count > 90:
                    scan_success = False
                    result_data = None
                    last_message = ""
                    patient_name = ""
            else:
                display = _draw_scan_frame(adjusted_frame.copy(), roi)

            try:
                _, _, win_w, win_h = cv2.getWindowImageRect("QR Scanner")
                if win_w > 0 and win_h > 0:
                    screen_w, screen_h = win_w, win_h
            except Exception:
                pass

            display = _resize_fill(display, screen_w, screen_h)

            if not scan_success:
                # Scale ROI y-coordinate to match resized display
                scale_y = screen_h / H if H > 0 else 1.0
                # Text nằm bên trong ROI, ngay dưới cạnh trên (cách viền 12px)
                roi_top_scaled = int(roi[1] * scale_y)
                roi_text_y = roi_top_scaled - 45
                display = _draw_text_centered_pil(
                    display,
                    "Đặt QR vào khung",
                    roi_text_y,
                    size=32,
                    color=(0, 220, 0),
                )

            cv2.imshow("QR Scanner", display)
            if _LEGACY_SCAN_STOP_EVENT.is_set():
                break
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        _LEGACY_SCAN_STOP_EVENT.clear()
        _hard_release_camera(cap, ("QR Scanner",))

    return result_data


class EventBus:
    """Lightweight thread-safe event bus with non-blocking callbacks."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[dict], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_name: str, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._subs.setdefault(event_name, []).append(callback)

    def emit(self, event_name: str, payload: dict) -> None:
        with self._lock:
            callbacks = list(self._subs.get(event_name, []))
        for cb in callbacks:
            threading.Thread(target=cb, args=(payload,), daemon=True).start()


class CameraService:
    """Dedicated camera capture thread that always keeps only the newest frame."""

    def __init__(self, camera_index: int | str, config: dict) -> None:
        self.camera_index = camera_index
        self.config = config
        self.frame_queue: Queue[tuple[int, np.ndarray]] = Queue(maxsize=1)
        self._latest_lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._latest_id = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self._cap = None
        self._frame_shape: tuple[int, int] | None = None
        self._roi: tuple[int, int, int, int] | None = None
        self._auto_camera_enabled = bool(self.config.get("auto_camera", True))
        self._use_windows_native_defaults = _use_windows_native_camera_defaults(self._auto_camera_enabled)
        if self._auto_camera_enabled:
            self._preview_alpha = float(AUTO_CAMERA_STATE_DEFAULTS["alpha"])
            self._preview_beta = int(round(AUTO_CAMERA_STATE_DEFAULTS["beta"]))
            self._auto_camera_state = _build_auto_camera_state()
        else:
            self._preview_alpha = max(1.0, float(self.config.get("contrast", 1.08)))
            self._preview_beta = int(self.config.get("brightness", 80)) - 50
            self._auto_camera_state = {}

    @property
    def frame_shape(self) -> tuple[int, int] | None:
        return self._frame_shape

    def set_roi(self, roi: tuple[int, int, int, int]) -> None:
        with self._latest_lock:
            self._roi = roi

    def get_preview_adjustment(self) -> tuple[float, int]:
        with self._latest_lock:
            return float(self._preview_alpha), int(self._preview_beta)

    def start(self) -> None:
        if self._running:
            return

        self._cap, first = _open_and_warmup_camera(
            camera_index=self.camera_index,
            config=self.config,
            auto_camera_enabled=self._auto_camera_enabled,
            use_windows_native_defaults=self._use_windows_native_defaults,
            default_width=640,
            default_height=480,
            default_fps=20,
            prefer_mjpg=False,
        )
        h, w = first.shape[:2]
        self._frame_shape = (h, w)
        self._latest_frame = first
        self._latest_id = 1

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self) -> None:
        assert self._cap is not None
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                continue

            if self._auto_camera_enabled:
                roi = self._get_auto_roi(frame.shape)
                alpha, beta, sharpness = _auto_adjust_exposure_for_roi(
                    frame,
                    roi,
                    self._auto_camera_state,
                )
                if not self._use_windows_native_defaults:
                    _rebalance_auto_exposure(self._cap, self._auto_camera_state)
                    _kick_autofocus_if_blurry(self._cap, self._auto_camera_state, sharpness)
                with self._latest_lock:
                    self._preview_alpha = alpha
                    self._preview_beta = beta

            with self._latest_lock:
                self._latest_id += 1
                frame_id = self._latest_id
                self._latest_frame = frame

            try:
                self.frame_queue.put_nowait((frame_id, frame))
            except Full:
                try:
                    self.frame_queue.get_nowait()
                except Empty:
                    pass
                try:
                    self.frame_queue.put_nowait((frame_id, frame))
                except Full:
                    pass

    def _get_auto_roi(self, frame_shape: tuple[int, ...]) -> tuple[int, int, int, int]:
        with self._latest_lock:
            if self._roi is not None:
                return self._roi

        frame_h, frame_w = frame_shape[:2]
        roi_scale = float(self.config.get("roi_scale", 0.7))
        roi_height_scale = float(self.config.get("roi_height_scale", roi_scale))
        roi_w = int(frame_w * roi_scale)
        roi_h = int(frame_h * roi_height_scale)
        roi_x = (frame_w - roi_w) // 2
        roi_y = (frame_h - roi_h) // 2
        return roi_x, roi_y, roi_w, roi_h

    def get_latest_frame(self) -> tuple[int, np.ndarray] | None:
        with self._latest_lock:
            if self._latest_frame is None:
                return None
            return self._latest_id, self._latest_frame.copy()

    def get_decode_frame(self, timeout: float = 0.05) -> tuple[int, np.ndarray] | None:
        try:
            return self.frame_queue.get(timeout=timeout)
        except Empty:
            return None

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            _hard_release_camera(self._cap, tuple())


class DecodeWorker:
    """ROI decode worker thread; emits QR_DETECTED events only."""

    def __init__(self, camera: CameraService, roi: tuple[int, int, int, int], bus: EventBus) -> None:
        self.camera = camera
        self.roi = roi
        self.bus = bus
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_payload = ""
        self._last_payload_ts = 0.0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        x, y, w, h = self.roi
        while self._running:
            packet = self.camera.get_decode_frame(timeout=0.05)
            if packet is None:
                continue
            frame_id, frame = packet
            roi_frame = frame[y:y + h, x:x + w]
            if roi_frame.size == 0:
                continue

            # Fast path: raw color decode first.
            data = _decode_qr([roi_frame])
            if not data:
                alpha, beta = self.camera.get_preview_adjustment()
                roi_decode = roi_frame
                if abs(alpha - 1.0) > 0.04 or abs(beta) > 4:
                    roi_decode = cv2.convertScaleAbs(roi_frame, alpha=alpha, beta=beta)
                gray = cv2.cvtColor(roi_decode, cv2.COLOR_BGR2GRAY)
                luma = float(np.mean(gray)) if gray.size else 128.0
                data = _decode_qr(_preprocess_for_qr(roi_decode, mean_luma=luma))

            if not data:
                continue

            now = time.time()
            if data == self._last_payload and (now - self._last_payload_ts) < 1.0:
                continue
            self._last_payload = data
            self._last_payload_ts = now

            self.bus.emit("QR_DETECTED", {"payload": data, "frame_id": frame_id, "ts": now})

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


class ScanController:
    """Business/state controller. Handles validation and emits UI_STATE events."""

    STATE_IDLE = "IDLE"
    STATE_SCANNING = "SCANNING"
    STATE_VALIDATING = "VALIDATING"
    STATE_SUCCESS = "SUCCESS"
    STATE_INVALID = "INVALID"
    STATE_CANCELLED = "CANCELLED"
    STATE_COOLDOWN = "COOLDOWN"

    def __init__(self, bus: EventBus, patients_path: str, appointments_path: str, cooldown_sec: float = 3.0) -> None:
        self.bus = bus
        self.patients_path = patients_path
        self.appointments_path = appointments_path
        self.cooldown_sec = cooldown_sec
        self.arrived_ignore_sec = 8.0

        self._state_lock = threading.Lock()
        self._state = self.STATE_IDLE
        self._message = ""
        self._patient_name = ""
        self._cooldown_kind = self.STATE_INVALID
        self._cooldown_until = 0.0
        self._ignore_payload_until: dict[str, float] = {}
        self._running = False
        self._tick_thread: threading.Thread | None = None

        self.bus.subscribe("QR_DETECTED", self._on_qr_detected)

    def start(self) -> None:
        self._running = True
        self._set_state(self.STATE_SCANNING, "Đưa QR vào khung")
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._tick_thread and self._tick_thread.is_alive():
            self._tick_thread.join(timeout=1.0)
        self._set_state(self.STATE_IDLE, "")

    def snapshot(self) -> dict:
        with self._state_lock:
            return {
                "state": self._state,
                "message": self._message,
                "patient_name": self._patient_name,
                "cooldown_kind": self._cooldown_kind,
            }

    def _set_state(self, state: str, message: str = "", patient_name: str = "") -> None:
        with self._state_lock:
            self._state = state
            self._message = message
            self._patient_name = patient_name
        self.bus.emit("UI_STATE", {"state": state, "message": message, "patient_name": patient_name})

    def _on_qr_detected(self, payload: dict) -> None:
        with self._state_lock:
            if self._state != self.STATE_SCANNING:
                return

        data = str(payload.get("payload", ""))

        # Nếu payload vừa được đánh dấu "arrived" gần đây thì bỏ qua luôn,
        # tránh nhảy text liên tục SCANNING <-> VALIDATING.
        now = time.time()
        with self._state_lock:
            ignore_until = self._ignore_payload_until.get(data, 0.0)
            if ignore_until > now:
                return
            # dọn cache hết hạn để dict không lớn dần
            expired = [k for k, v in self._ignore_payload_until.items() if v <= now]
            for k in expired:
                self._ignore_payload_until.pop(k, None)

        self._set_state(self.STATE_VALIDATING, "Đang xác thực mã QR...")

        if not _is_likely_qr_payload(data):
            self._set_state(self.STATE_INVALID, "Mã QR không hợp lệ vui lòng thử lại")
            self._enter_cooldown(self.STATE_INVALID)
            return

        message, patient_name = _process_payload_and_update(
            data,
            patients_path=self.patients_path,
            appointments_path=self.appointments_path,
        )

        lower = message.lower() if message else ""
        if _is_arrived_checkin_message(message):
            # Safe re-scan: show check-in info, then ignore same payload for a short TTL.
            with self._state_lock:
                self._ignore_payload_until[data] = time.time() + self.arrived_ignore_sec
            self._set_state(self.STATE_SUCCESS, message, patient_name)
            self._enter_cooldown(self.STATE_SUCCESS)
        elif (not message) or ("thành công" in lower) or ("đã cập nhật" in lower):
            greet = (
                f"Chào mừng quý khách {patient_name} đã đến phòng khám"
                if patient_name else
                "Chào mừng quý khách đã đến phòng khám"
            )
            self._set_state(self.STATE_SUCCESS, greet, patient_name)
            self._enter_cooldown(self.STATE_SUCCESS)
        elif ("hoàn tất" in lower) or ("hoan tat" in lower) or ("đã khám" in lower):
            self._set_state(self.STATE_INVALID, message)
            self._enter_cooldown(self.STATE_INVALID)
        elif ("chưa đến ngày khám" in lower) or ("đã hủy" in lower) or ("hủy" in lower) or ("đã quá hẹn" in lower) or ("qua han" in lower) or ("quá hạn" in lower) or ("expired" in lower):
            self._set_state(self.STATE_CANCELLED, message)
            self._enter_cooldown(self.STATE_CANCELLED)
        else:
            self._set_state(self.STATE_INVALID, message)
            self._enter_cooldown(self.STATE_INVALID)

    def _enter_cooldown(self, from_state: str) -> None:
        with self._state_lock:
            self._cooldown_until = time.time() + self.cooldown_sec
            self._cooldown_kind = from_state
            self._state = self.STATE_COOLDOWN
            state_payload = {
                "state": self.STATE_COOLDOWN,
                "message": self._message,
                "patient_name": self._patient_name,
                "cooldown_kind": self._cooldown_kind,
            }
        self.bus.emit("UI_STATE", state_payload)

    def _tick_loop(self) -> None:
        while self._running:
            with self._state_lock:
                should_resume = self._state == self.STATE_COOLDOWN and time.time() >= self._cooldown_until
            if should_resume:
                self._set_state(self.STATE_SCANNING, "Đưa QR vào khung")
            time.sleep(0.05)


class UIRenderer:
    """Display loop only: renders camera + overlays from state snapshot."""

    def __init__(self, camera: CameraService, controller: ScanController, roi: tuple[int, int, int, int]) -> None:
        self.camera = camera
        self.controller = controller
        self.roi = roi
        self._running = False

    def run(self) -> None:
        shape = self.camera.frame_shape
        if shape is None:
            raise RuntimeError("Camera chưa sẵn sàng")
        h, w = shape

        keep_ratio_flag = getattr(cv2, "WINDOW_KEEPRATIO", cv2.WINDOW_NORMAL)
        cv2.namedWindow("QR Scanner", cv2.WINDOW_NORMAL | keep_ratio_flag)
        try:
            cv2.setWindowProperty("QR Scanner", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        except Exception:
            pass
        try:
            cv2.setWindowProperty("QR Scanner", cv2.WND_PROP_ASPECT_RATIO, keep_ratio_flag)
        except Exception:
            pass

        self._running = True
        while self._running:
            latest = self.camera.get_latest_frame()
            if latest is None:
                continue
            _, frame = latest
            state = self.controller.snapshot()

            display = self._render_state(frame, state, w, h)
            display = _apply_display_zoom_out(display)
            cv2.imshow("QR Scanner", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                self._running = False

        cv2.destroyWindow("QR Scanner")

    def stop(self) -> None:
        self._running = False

    def _render_state(self, frame: np.ndarray, state: dict, w: int, h: int) -> np.ndarray:
        mode = state.get("state", ScanController.STATE_SCANNING)
        message = str(state.get("message", ""))
        cooldown_kind = state.get("cooldown_kind", ScanController.STATE_INVALID)
        is_success_display = (mode == ScanController.STATE_SUCCESS) or (
            mode == ScanController.STATE_COOLDOWN and cooldown_kind == ScanController.STATE_SUCCESS
        )
        is_cancelled_display = (mode == ScanController.STATE_CANCELLED) or (
            mode == ScanController.STATE_COOLDOWN and cooldown_kind == ScanController.STATE_CANCELLED
        )

        # Render result screens at high resolution for crisp text
        render_w = max(w, 1920)
        render_h = max(h, 1080)

        if mode in {
            ScanController.STATE_SUCCESS,
            ScanController.STATE_INVALID,
            ScanController.STATE_CANCELLED,
            ScanController.STATE_COOLDOWN,
        }:
            canvas = np.full((render_h, render_w, 3), 255, dtype=np.uint8)

            # Đẹp hóa màn hình đã check in và parse message theo dạng linh hoạt.
            if _is_arrived_checkin_message(message):
                checkin_time, queue_number = _extract_checkin_info(message)
                return _render_result_screen(
                    render_w,
                    render_h,
                    "already_checked_in",
                    f"Bạn đã check in vào lúc {checkin_time}",
                    f"Số thứ tự: {queue_number}",
                )

            if is_success_display:
                return _render_result_screen(
                    render_w,
                    render_h,
                    "success",
                    message or "Chào mừng quý khách đã đến phòng khám",
                )

            if is_cancelled_display:
                return _render_result_screen(
                    render_w,
                    render_h,
                    "cancelled",
                    message or "Lịch của bạn đã hủy vui lòng kiểm tra lại",
                )

            return _render_result_screen(
                render_w,
                render_h,
                "invalid_qr",
                "Mã QR không hợp lệ",
                message or "Vui lòng thử lại",
            )

        alpha, beta = self.camera.get_preview_adjustment()
        display_live = cv2.convertScaleAbs(frame, alpha=alpha, beta=beta)
        display_live = _draw_scan_frame(display_live, self.roi)
        # Text nằm phía trên ROI top, cách viền ~50px
        roi_text_y = max(10, self.roi[1] - 50)
        if mode == ScanController.STATE_VALIDATING:
            return _draw_text_centered_pil(display_live, "Giữ nguyên mã QR để quét", roi_text_y, size=26, color=(0, 220, 0))
        return _draw_text_centered_pil(display_live, "Đặt QR vào khung", roi_text_y, size=28, color=(0, 220, 0))


class KioskScannerApp:
    """Compose CameraService -> DecodeWorker -> EventBus -> ScanController -> UIRenderer."""

    def __init__(
        self,
        camera_index: int | str | None = None,
        patients_path: str = "patients",
        appointments_path: str = "appointment_new",
        config: dict | None = None,
    ) -> None:
        self.config = config or _load_camera_config()
        if camera_index is None:
            camera_index = self.config.get("camera_index", 0)
        self.camera_index = camera_index
        self.patients_path = patients_path
        self.appointments_path = appointments_path

        self.bus = EventBus()
        self.camera = CameraService(camera_index=self.camera_index, config=self.config)
        self.controller: ScanController | None = None
        self.decoder: DecodeWorker | None = None
        self.ui: UIRenderer | None = None

    def start(self) -> None:
        self.camera.start()
        shape = self.camera.frame_shape
        if shape is None:
            raise RuntimeError("Không lấy được kích thước frame camera")
        h, w = shape

        roi_scale = self.config.get("roi_scale", 0.7)
        roi_height_scale = self.config.get("roi_height_scale", roi_scale)
        roi_w = int(w * roi_scale)
        roi_h = int(h * roi_height_scale)
        roi_x = (w - roi_w) // 2
        roi_y = (h - roi_h) // 2
        roi = (roi_x, roi_y, roi_w, roi_h)
        self.camera.set_roi(roi)

        self.controller = ScanController(
            bus=self.bus,
            patients_path=self.patients_path,
            appointments_path=self.appointments_path,
            cooldown_sec=3.0,
        )
        self.decoder = DecodeWorker(camera=self.camera, roi=roi, bus=self.bus)
        self.ui = UIRenderer(camera=self.camera, controller=self.controller, roi=roi)

        self.controller.start()
        self.decoder.start()

    def run(self) -> None:
        if self.ui is None:
            raise RuntimeError("Scanner chưa được start")
        self.ui.run()

    def stop(self) -> None:
        if self.ui:
            self.ui.stop()
        if self.decoder:
            self.decoder.stop()
        if self.controller:
            self.controller.stop()
        self.camera.stop()


_ACTIVE_SCANNER: KioskScannerApp | None = None
_LEGACY_SCAN_STOP_EVENT = threading.Event()


def request_legacy_scan_stop() -> None:
    """Ask the legacy OpenCV scan loop to exit on its next UI tick."""
    _LEGACY_SCAN_STOP_EVENT.set()


def start_scanner(
    camera_index: int | str | None = None,
    patients_path: str = "patients",
    appointments_path: str = "appointment_new",
    config: dict | None = None,
) -> KioskScannerApp:
    global _ACTIVE_SCANNER
    scanner = KioskScannerApp(
        camera_index=camera_index,
        patients_path=patients_path,
        appointments_path=appointments_path,
        config=config,
    )
    scanner.start()
    _ACTIVE_SCANNER = scanner
    return scanner


def stop_scanner(scanner: KioskScannerApp | None = None) -> None:
    global _ACTIVE_SCANNER
    request_legacy_scan_stop()
    target = scanner or _ACTIVE_SCANNER
    if not target:
        return
    target.stop()
    if target is _ACTIVE_SCANNER:
        _ACTIVE_SCANNER = None


def scan_from_camera(
    camera_index: int | str | None = None,
    patients_path: str = "patients",
    appointments_path: str = "appointment_new",
    config: dict | None = None,
) -> str | None:
    """Backward-compatible entrypoint using the proven Copy-2 scan loop."""
    return _legacy_scan_from_camera(
        camera_index=camera_index,
        patients_path=patients_path,
        appointments_path=appointments_path,
        config=config,
    )
