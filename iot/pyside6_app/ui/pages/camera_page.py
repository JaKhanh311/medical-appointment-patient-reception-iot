"""
Camera setup page — ported from newUI/camera_roi.html.
Camera detection + configure ROI preview via qr_scan._configure_camera_preview.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QRunnable, QThreadPool, QObject, Signal, QProcess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QComboBox, QScrollArea, QGridLayout,
    QSlider, QCheckBox, QSizePolicy, QSpinBox,
)

from config.theme import C
from services.auth_service import load_settings, save_settings

_IOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_IOT_DIR) not in sys.path:
    sys.path.insert(0, str(_IOT_DIR))


class _ScanCameraSignals(QObject):
    done = Signal(list)  # list of dict


class _ScanCameraWorker(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = _ScanCameraSignals()
        # Prevent Qt from auto-deleting the QRunnable before signal emission completes.
        self.setAutoDelete(False)

    def run(self) -> None:
        cameras: list[dict] = []
        try:
            if os.name == "nt":
                cameras = _scan_cameras_windows()
            else:
                cameras = _scan_cameras_linux()
        except Exception:
            pass
        # Guard against the signals object being garbage-collected if the parent
        # widget closed before this background thread finished.
        try:
            signals = getattr(self, "signals", None)
            if signals is not None:
                signals.done.emit(cameras)
        except RuntimeError:
            # _ScanCameraSignals was deleted (parent closed). Safe to ignore.
            pass


def _scan_cameras_windows() -> list[dict]:
    import cv2
    import subprocess

    # Silence noisy backend probe warnings (DSHOW/MSMF) while enumerating indexes.
    prev_level = None
    try:
        if hasattr(cv2, "getLogLevel"):
            prev_level = cv2.getLogLevel()
        if hasattr(cv2, "setLogLevel"):
            cv2.setLogLevel(0)
        elif hasattr(cv2, "utils") and hasattr(cv2.utils, "logging"):
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        prev_level = None

    wmi_names: list[str] = []
    try:
        flags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            ["wmic", "path", "Win32_PnPEntity", "where", "PNPClass='Camera'", "get", "Name", "/format:list"],
            capture_output=True, text=True, timeout=8, creationflags=flags,
        )
        wmi_names = [
            line.split("=", 1)[1].strip()
            for line in result.stdout.splitlines()
            if line.startswith("Name=") and line.split("=", 1)[1].strip()
        ]
    except Exception:
        pass

    cameras: list[dict] = []
    seen_devices: set[str] = set()
    backends: list[int | None] = []
    for backend_name in ("CAP_DSHOW", "CAP_MSMF"):
        backend = getattr(cv2, backend_name, None)
        if backend is not None:
            backends.append(backend)
    backends.append(None)

    for idx in range(10):
        opened = False
        for backend in backends:
            cap = cv2.VideoCapture(idx) if backend is None else cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                cap.release()
                continue
            ok, _ = cap.read()
            cap.release()
            if ok:
                opened = True
                break
        if not opened:
            continue

        device = str(idx)
        if device in seen_devices:
            continue
        seen_devices.add(device)
        name = wmi_names[len(cameras)] if len(cameras) < len(wmi_names) else f"Camera {idx}"
        cameras.append({"index": idx, "device": device, "name": name})

    try:
        if prev_level is not None and hasattr(cv2, "setLogLevel"):
            cv2.setLogLevel(prev_level)
    except Exception:
        pass

    return cameras


def _scan_cameras_linux() -> list[dict]:
    cameras: list[dict] = []
    base = "/sys/class/video4linux"
    if not os.path.exists(base):
        return cameras
    for dev in sorted(os.listdir(base)):
        device_path = f"/dev/{dev}"
        if not os.path.exists(device_path):
            continue
        try:
            device_sys = f"{base}/{dev}/device"
            real_path = os.path.realpath(device_sys)
            is_usb = "usb" in real_path.lower()
            name_file = f"{base}/{dev}/name"
            with open(name_file) as f:
                name = f.read().strip()
            index_file = f"{base}/{dev}/index"
            stream_index = 0
            if os.path.exists(index_file):
                try:
                    with open(index_file) as f:
                        stream_index = int(f.read().strip())
                except Exception:
                    stream_index = 0
            cameras.append({"index": stream_index, "device": device_path, "name": name, "usb": is_usb})
        except Exception:
            pass
    cameras.sort(key=lambda cam: (0 if cam.get("usb") else 1, int(cam.get("index", 0) or 0), str(cam.get("device", ""))))
    return cameras


# (no QRunnable needed — config preview runs as a child QProcess)


class CameraPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._settings = load_settings()
        self._cameras: list[dict] = []
        self._config_process: QProcess | None = None
        self._setup_ui()
        self._scan_cameras()

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setStyleSheet(f"background: {C['background']};")
        main = QVBoxLayout(content)
        main.setContentsMargins(24, 24, 24, 24)
        main.setSpacing(24)

        # ── Header ────────────────────────────────────────────────────────────
        hdr_col = QVBoxLayout()
        title = QLabel("Camera Setup")
        title.setObjectName("heading1")
        hdr_col.addWidget(title)
        sub = QLabel("Chọn camera và cấu hình thông số ROI cho quét QR.")
        sub.setObjectName("bodyMuted")
        hdr_col.addWidget(sub)
        main.addLayout(hdr_col)

        # ── Camera selection card ─────────────────────────────────────────────
        cam_card = QFrame()
        cam_card.setObjectName("card")
        cam_layout = QVBoxLayout(cam_card)
        cam_layout.setContentsMargins(20, 20, 20, 20)
        cam_layout.setSpacing(16)

        cam_title = QLabel("Camera Device")
        cam_title.setObjectName("heading2")
        cam_layout.addWidget(cam_title)

        cam_row = QHBoxLayout()
        cam_row.setSpacing(12)

        self._cam_combo = QComboBox()
        self._cam_combo.setFixedHeight(36)
        self._cam_combo.currentIndexChanged.connect(self._on_camera_selected)
        cam_row.addWidget(self._cam_combo, stretch=1)

        self._scan_btn = QPushButton("🔍  Quét camera")
        self._scan_btn.setObjectName("secondaryBtn")
        self._scan_btn.setFixedHeight(36)
        self._scan_btn.clicked.connect(self._scan_cameras)
        cam_row.addWidget(self._scan_btn)

        cam_layout.addLayout(cam_row)

        self._cam_status = QLabel("Đang quét camera…")
        self._cam_status.setObjectName("bodyMuted")
        cam_layout.addWidget(self._cam_status)
        main.addWidget(cam_card)

        # ── Scanner settings card ─────────────────────────────────────────────
        settings_card = QFrame()
        settings_card.setObjectName("card")
        s_layout = QVBoxLayout(settings_card)
        s_layout.setContentsMargins(20, 20, 20, 20)
        s_layout.setSpacing(16)

        s_title = QLabel("Scanner Settings")
        s_title.setObjectName("heading2")
        s_layout.addWidget(s_title)

        grid = QGridLayout()
        grid.setSpacing(16)

        # Patients path
        grid.addWidget(self._make_label("Patients collection path"), 0, 0)
        self._patients_combo = QComboBox()
        self._patients_combo.addItems(["patients", "Patients", "benh_nhan"])
        self._patients_combo.setEditable(True)
        self._patients_combo.setCurrentText(
            self._settings.get("scanner", {}).get("patients_path", "patients")
        )
        grid.addWidget(self._patients_combo, 0, 1)

        # Appointments path
        grid.addWidget(self._make_label("Appointments collection path"), 1, 0)
        self._appts_combo = QComboBox()
        self._appts_combo.addItems(["appointments", "Appointments", "lich_kham"])
        self._appts_combo.setEditable(True)
        self._appts_combo.setCurrentText(
            self._settings.get("scanner", {}).get("appointments_path", "appointments")
        )
        grid.addWidget(self._appts_combo, 1, 1)

        s_layout.addLayout(grid)
        main.addWidget(settings_card)

        # ── Configure ROI button ──────────────────────────────────────────────
        roi_card = QFrame()
        roi_card.setObjectName("card")
        roi_layout = QVBoxLayout(roi_card)
        roi_layout.setContentsMargins(20, 20, 20, 20)
        roi_layout.setSpacing(12)

        roi_title = QLabel("Camera ROI Configuration")
        roi_title.setObjectName("heading2")
        roi_layout.addWidget(roi_title)

        roi_desc = QLabel(
            "Mở cửa sổ cấu hình camera trực tiếp (OpenCV). "
            "Dùng phím W/S để điều hướng, A/L để thay đổi giá trị. "
            "Nhấn P để áp dụng QR Preset tối ưu. ESC để lưu và đóng."
        )
        roi_desc.setObjectName("bodyMuted")
        roi_desc.setWordWrap(True)
        roi_layout.addWidget(roi_desc)

        btn_row = QHBoxLayout()
        self._config_btn = QPushButton("⚙  Cấu hình camera (OpenCV)")
        self._config_btn.setObjectName("primaryBtn")
        self._config_btn.setFixedHeight(40)
        self._config_btn.clicked.connect(self._open_config_preview)
        btn_row.addWidget(self._config_btn)

        reset_btn = QPushButton("🔄  Reset config")
        reset_btn.setObjectName("secondaryBtn")
        reset_btn.setFixedHeight(40)
        reset_btn.clicked.connect(self._reset_config)
        btn_row.addWidget(reset_btn)
        roi_layout.addLayout(btn_row)

        self._roi_status = QLabel("")
        self._roi_status.setObjectName("bodyMuted")
        roi_layout.addWidget(self._roi_status)
        main.addWidget(roi_card)

        # ── Save settings ─────────────────────────────────────────────────────
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = QPushButton("  💾  Lưu cài đặt")
        save_btn.setObjectName("primaryBtn")
        save_btn.setFixedHeight(40)
        save_btn.clicked.connect(self._save_settings)
        save_row.addWidget(save_btn)
        main.addLayout(save_row)

        main.addStretch()
        scroll.setWidget(content)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    @staticmethod
    def _make_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {C['on_surface_variant']}; font-size: 12px; background: transparent; border: none;"
        )
        return lbl

    def _scan_cameras(self) -> None:
        self._cam_status.setText("Đang quét camera…")
        self._cam_combo.clear()
        self._scan_btn.setEnabled(False)
        worker = _ScanCameraWorker()
        worker.signals.done.connect(self._on_cameras_found)
        # Keep references on `self` so neither the QRunnable nor its signals
        # object can be garbage-collected before the background thread finishes.
        self._scan_worker = worker
        self._scan_worker_signals = worker.signals
        self._pool.start(worker)

    @Slot(list)
    def _on_cameras_found(self, cameras: list) -> None:
        self._scan_btn.setEnabled(True)
        self._cameras = cameras
        if not cameras:
            self._cam_status.setText("Không tìm thấy camera.")
            self._cam_combo.addItem("0 — Default")
            return
        for cam in cameras:
            label = f"{cam['device']} — {cam['name']}"
            self._cam_combo.addItem(label)
        saved = self._settings.get("scanner", {}).get("camera_index", "")
        if saved:
            for i, cam in enumerate(cameras):
                if str(cam["device"]) == str(saved):
                    self._cam_combo.setCurrentIndex(i)
                    break
        else:
            self._cam_combo.setCurrentIndex(0)
        self._cam_status.setText(f"Tìm thấy {len(cameras)} camera.")

    @Slot(int)
    def _on_camera_selected(self, index: int) -> None:
        if 0 <= index < len(self._cameras):
            cam_index = self._cameras[index]["device"]
            self._settings.setdefault("scanner", {})["camera_index"] = str(cam_index)
            save_settings(self._settings)
            self._cam_status.setText(f"Đã chọn camera: {cam_index}")

    def _get_selected_camera_index(self):
        idx = self._cam_combo.currentIndex()
        if 0 <= idx < len(self._cameras):
            return self._cameras[idx]["device"]
        return 0

    def _open_config_preview(self) -> None:
        # Nếu helper process đang chạy, không mở thêm
        if self._config_process and self._config_process.state() != QProcess.ProcessState.NotRunning:
            self._roi_status.setText("Cửa sổ cấu hình đang mở…")
            return

        cam_index = self._get_selected_camera_index()
        helper = str(Path(__file__).resolve().parent.parent.parent / "_camera_config_helper.py")

        # Đảm bảo giải phóng process cũ nếu còn sót
        if self._config_process:
            try:
                self._config_process.kill()
                self._config_process.waitForFinished(2000)
            except Exception:
                pass
        self._config_process = QProcess(self)
        self._config_process.finished.connect(self._on_config_process_finished)
        self._config_process.setProgram(sys.executable)
        from config.theme import get_theme_name
        current_theme = get_theme_name()
        self._config_process.setArguments([helper, str(cam_index), current_theme])

        self._config_btn.setEnabled(False)
        self._roi_status.setText("Đang mở cửa sổ cấu hình camera… (ESC để lưu và đóng)")
        self._config_process.start()

    @Slot(int, object)
    def _on_config_process_finished(self, exit_code: int, _exit_status) -> None:
        self._config_btn.setEnabled(True)
        if exit_code == 0:
            stdout = bytes(self._config_process.readAllStandardOutput()).decode(errors="replace").strip()
            self._roi_status.setText(f"✓ {stdout}" if stdout else "✓ Cấu hình đã lưu thành công.")
        else:
            stderr = bytes(self._config_process.readAllStandardError()).decode(errors="replace").strip()
            self._roi_status.setText(f"Lỗi: {stderr or 'exit code ' + str(exit_code)}")

    def _reset_config(self) -> None:
        try:
            from qr_scan import _reset_camera_config
            _reset_camera_config()
            self._roi_status.setText("✓ Đã reset về cài đặt mặc định.")
        except Exception as exc:
            self._roi_status.setText(f"Lỗi: {exc}")

    def _save_settings(self) -> None:
        cam_index = self._get_selected_camera_index()
        self._settings.setdefault("scanner", {})["camera_index"] = str(cam_index)
        self._settings["scanner"]["patients_path"] = self._patients_combo.currentText()
        self._settings["scanner"]["appointments_path"] = self._appts_combo.currentText()
        save_settings(self._settings)
        self._cam_status.setText("✓ Đã lưu cài đặt.")

    @Slot(str)
    def log_line(self, _msg: str) -> None:
        pass
