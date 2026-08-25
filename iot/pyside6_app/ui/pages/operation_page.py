"""
Operation page — QR scan console.
Runs the scan loop as a SUBPROCESS (QProcess) instead of QThread to avoid
Qt event-loop conflicts on Linux/Raspberry Pi where OpenCV is built with
Qt backend (QBasicTimer errors).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Slot, Signal, QObject, QProcess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QGridLayout, QScrollArea, QSizePolicy,
)

from config.theme import C
from services.auth_service import load_settings

_IOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_IOT_DIR) not in sys.path:
    sys.path.insert(0, str(_IOT_DIR))


# ── Metric card ───────────────────────────────────────────────────────────────

class _MetricCard(QFrame):
    def __init__(self, mono_label: str, icon: str, val_color: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedHeight(100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        lbl = QLabel(f"{icon}  {mono_label.upper()}")
        lbl.setObjectName("labelMono")
        top.addWidget(lbl)
        layout.addLayout(top)

        self._val_lbl = QLabel("0")
        self._val_lbl.setStyleSheet(
            f"color: {val_color}; font-size: 28px; font-weight: 700; background: transparent; border: none;"
        )
        layout.addWidget(self._val_lbl)

    def set_value(self, v: str) -> None:
        self._val_lbl.setText(v)


# ── Operation Page ────────────────────────────────────────────────────────────

class OperationPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = load_settings()
        self._scan_process: QProcess | None = None
        self._is_scanning = False
        self._scan_count = 0
        self._error_count = 0
        self._log_lines: list[str] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # ── Left: controls ────────────────────────────────────────────────────
        left_widget = QWidget()
        left_widget.setStyleSheet(f"background: {C['background']};")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(24, 24, 24, 24)
        left_layout.setSpacing(20)

        # Header
        session_lbl = QLabel("Active Session")
        session_lbl.setObjectName("heading2")
        left_layout.addWidget(session_lbl)

        status_row = QHBoxLayout()
        self._online_lbl = QLabel("● SCANNER IDLE")
        self._online_lbl.setStyleSheet(
            f"color: {C['outline']}; font-size: 11px; font-weight: 600; "
            f"font-family: 'JetBrains Mono', monospace; background: transparent; border: none;"
        )
        status_row.addWidget(self._online_lbl)
        status_row.addStretch()
        left_layout.addLayout(status_row)

        # Metrics grid
        metrics = QGridLayout()
        metrics.setSpacing(12)
        self._scans_card = _MetricCard("Scans", "📷", C["on_surface"])
        self._errors_card = _MetricCard("Errors", "⚠", C["error"])
        self._status_card = _MetricCard("Status", "✓", C["secondary"])
        metrics.addWidget(self._scans_card, 0, 0)
        metrics.addWidget(self._errors_card, 0, 1)
        metrics.addWidget(self._status_card, 1, 0, 1, 2)
        left_layout.addLayout(metrics)

        # Hardware controls card
        ctrl_card = QFrame()
        ctrl_card.setObjectName("card")
        ctrl_layout = QVBoxLayout(ctrl_card)
        ctrl_layout.setContentsMargins(16, 16, 16, 16)
        ctrl_layout.setSpacing(12)

        ctrl_header = QLabel("HARDWARE CONTROLS")
        ctrl_header.setObjectName("labelMono")
        ctrl_layout.addWidget(ctrl_header)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {C['outline_variant']}; border: none;")
        ctrl_layout.addWidget(sep)

        # Big start/stop button
        self._scan_btn = QPushButton("▶  START SCAN")
        self._scan_btn.setObjectName("primaryBtn")
        self._scan_btn.setFixedHeight(52)
        self._scan_btn.setStyleSheet(
            f"QPushButton {{ background: {C['primary']}; color: {C['on_primary']}; "
            f"border: none; border-radius: 8px; font-size: 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {C['primary_container']}; color: white; }}"
            f"QPushButton:disabled {{ background: {C['outline_variant']}; color: {C['outline']}; }}"
        )
        self._scan_btn.clicked.connect(self._toggle_scan)
        ctrl_layout.addWidget(self._scan_btn)

        # Secondary buttons row
        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(8)
        save_cfg_btn = QPushButton("💾 Save Config")
        save_cfg_btn.setObjectName("secondaryBtn")
        save_cfg_btn.clicked.connect(self._save_config)
        secondary_row.addWidget(save_cfg_btn)

        check_btn = QPushButton("📡 Check Conn.")
        check_btn.setObjectName("secondaryBtn")
        check_btn.clicked.connect(self._check_connection)
        secondary_row.addWidget(check_btn)
        ctrl_layout.addLayout(secondary_row)

        clear_log_btn = QPushButton("🗑  Clear Log")
        clear_log_btn.setObjectName("secondaryBtn")
        clear_log_btn.clicked.connect(self._clear_log)
        ctrl_layout.addWidget(clear_log_btn)

        left_layout.addWidget(ctrl_card)
        left_layout.addStretch()
        main.addWidget(left_widget, stretch=2)

        # ── Right: system log ─────────────────────────────────────────────────
        right_widget = QWidget()
        right_widget.setStyleSheet(
            f"background: {C['surface_container_low']}; "
            f"border-left: 1px solid {C['outline_variant']};"
        )
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        log_header = QFrame()
        log_header.setFixedHeight(44)
        log_header.setStyleSheet(
            f"background: {C['surface_container_high']}; "
            f"border-bottom: 1px solid {C['outline_variant']};"
        )
        lh_layout = QHBoxLayout(log_header)
        lh_layout.setContentsMargins(16, 0, 12, 0)
        terminal_title = QLabel("⬛  SYSTEM EVENT LOG")
        terminal_title.setObjectName("labelMono")
        lh_layout.addWidget(terminal_title)
        lh_layout.addStretch()
        right_layout.addWidget(log_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._log_lbl = QLabel()
        self._log_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._log_lbl.setWordWrap(True)
        self._log_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._log_lbl.setContentsMargins(12, 12, 12, 12)
        self._log_lbl.setStyleSheet(
            f"background: {C['surface_container_lowest']}; color: {C['on_surface_variant']}; "
            f"font-family: 'JetBrains Mono', monospace; font-size: 12px; border: none;"
        )
        scroll.setWidget(self._log_lbl)
        scroll.setStyleSheet(f"QScrollArea {{ background: {C['surface_container_lowest']}; border: none; }}")
        right_layout.addWidget(scroll)
        self._log_scroll = scroll

        main.addWidget(right_widget, stretch=1)

        # Initial log
        self.log_line("[INFO] QR Scanner Pro khoi dong thanh cong.")
        self.log_line("[INFO] Nhan START SCAN de bat dau quet.")
        self._update_metrics()

    # ── Scan control (QProcess based) ────────────────────────────────────────

    def _toggle_scan(self) -> None:
        if self._is_scanning:
            self._stop_scan()
        else:
            self._start_scan()

    def _start_scan(self) -> None:
        self._settings = load_settings()
        scanner = self._settings.get("scanner", {})
        cam_index = scanner.get("camera_index", 0)
        if not cam_index:
            cam_index = 0
        patients = scanner.get("patients_path", "patients")
        appointments = scanner.get("appointments_path", "appointment_new")

        # If a previous process is still alive, kill it first
        if self._scan_process and self._scan_process.state() != QProcess.ProcessState.NotRunning:
            try:
                self._scan_process.kill()
                self._scan_process.waitForFinished(1500)
            except Exception:
                pass
            self._scan_process = None

        helper = str(Path(__file__).resolve().parent.parent.parent / "_scan_helper.py")

        self._scan_process = QProcess(self)
        self._scan_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._scan_process.readyReadStandardOutput.connect(self._on_scan_output)
        self._scan_process.finished.connect(self._on_scan_finished)
        self._scan_process.setProgram(sys.executable)
        self._scan_process.setArguments([helper, str(cam_index), patients, appointments])

        self._is_scanning = True
        self._scan_btn.setText("⏹  STOP SCAN")
        self._scan_btn.setStyleSheet(
            f"QPushButton {{ background: {C['error_container']}; color: {C['error']}; "
            f"border: none; border-radius: 8px; font-size: 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: #b00008; color: white; }}"
        )
        self._online_lbl.setText("● SCANNER ONLINE")
        self._online_lbl.setStyleSheet(
            f"color: {C['secondary']}; font-size: 11px; font-weight: 600; "
            f"font-family: 'JetBrains Mono', monospace; background: transparent; border: none;"
        )

        self._scan_process.start()
        self.log_line(f"[INFO] Scanner khoi dong (subprocess) - camera: {cam_index}")

    def _stop_scan(self) -> None:
        self.log_line("[INFO] Dang dung scanner...")
        if self._scan_process and self._scan_process.state() != QProcess.ProcessState.NotRunning:
            try:
                self._scan_process.terminate()
                if not self._scan_process.waitForFinished(2000):
                    self._scan_process.kill()
                    self._scan_process.waitForFinished(1000)
            except Exception as exc:
                self.log_line(f"[WARN] Loi dung scanner: {exc}")

    @Slot()
    def _on_scan_output(self) -> None:
        if not self._scan_process:
            return
        try:
            data = bytes(self._scan_process.readAllStandardOutput()).decode(errors="replace")
        except Exception:
            return
        for line in data.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            lower = line.lower()
            if "[ok]" in lower or "thanh cong" in lower or "thành công" in lower or "đã cập nhật" in lower:
                self._scan_count += 1
            if "[fail]" in lower or "loi" in lower or "lỗi" in lower or "error" in lower:
                self._error_count += 1
            self.log_line(line)
        self._update_metrics()

    @Slot(int, object)
    def _on_scan_finished(self, exit_code: int = 0, _exit_status=None) -> None:
        self._is_scanning = False
        self._scan_btn.setText("▶  START SCAN")
        self._scan_btn.setStyleSheet(
            f"QPushButton {{ background: {C['primary']}; color: {C['on_primary']}; "
            f"border: none; border-radius: 8px; font-size: 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {C['primary_container']}; color: white; }}"
        )
        self._online_lbl.setText("● SCANNER IDLE")
        self._online_lbl.setStyleSheet(
            f"color: {C['outline']}; font-size: 11px; font-weight: 600; "
            f"font-family: 'JetBrains Mono', monospace; background: transparent; border: none;"
        )
        self._scan_process = None
        self.log_line(f"[INFO] Scanner da dung (exit={exit_code}).")

    def shutdown(self, wait_ms: int = 3000) -> None:
        if self._scan_process and self._scan_process.state() != QProcess.ProcessState.NotRunning:
            try:
                self._scan_process.terminate()
                if not self._scan_process.waitForFinished(wait_ms):
                    self._scan_process.kill()
                    self._scan_process.waitForFinished(1000)
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def _save_config(self) -> None:
        from services.auth_service import save_settings
        save_settings(self._settings)
        self.log_line("[OK] Da luu cau hinh.")

    def _check_connection(self) -> None:
        self.log_line("[INFO] Kiem tra ket noi Firebase...")
        try:
            from firebase_conn import get_db_ref
            ref = get_db_ref("/")
            ref.get()
            self.log_line("[OK] Ket noi Firebase thanh cong.")
        except Exception as exc:
            self.log_line(f"[FAIL] Ket noi that bai: {exc}")

    def _clear_log(self) -> None:
        self._log_lines.clear()
        self._log_lbl.setText("")

    def _update_metrics(self) -> None:
        self._scans_card.set_value(str(self._scan_count))
        self._errors_card.set_value(str(self._error_count))
        rate = "100%" if self._scan_count == 0 else \
               f"{(self._scan_count / (self._scan_count + self._error_count) * 100):.1f}%"
        self._status_card.set_value(rate)

    @Slot(str)
    def log_line(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        lower = msg.lower()
        if "[ok]" in lower or "thành công" in lower or "thanh cong" in lower:
            level_color = C["secondary"]
        elif "[fail]" in lower or "lỗi" in lower or "loi" in lower or "error" in lower:
            level_color = C["error"]
        elif "[warn]" in lower:
            level_color = C["tertiary"]
        else:
            level_color = C["on_surface_variant"]

        entry = (
            f'<span style="color:{C["outline"]}">[{ts}]</span> '
            f'<span style="color:{level_color}">{msg}</span><br>'
        )
        self._log_lines.append(entry)
        if len(self._log_lines) > 500:
            self._log_lines = self._log_lines[-500:]
        self._log_lbl.setText("".join(self._log_lines))
        # Auto-scroll to bottom
        sb = self._log_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
