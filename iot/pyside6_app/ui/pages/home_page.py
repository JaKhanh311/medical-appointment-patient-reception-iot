"""
Home page — system overview + event log.
Ported from newUI/home.html.
"""
from __future__ import annotations

import psutil
from datetime import datetime

from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QScrollArea, QGridLayout, QSizePolicy,
)

from config.theme import C


class _MetricCard(QFrame):
    def __init__(self, mono_label: str, icon: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(96)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        top = QHBoxLayout()
        mono = QLabel(mono_label.upper())
        mono.setObjectName("labelMono")
        top.addWidget(mono)
        top.addStretch()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"color: {color}; font-size: 15px; background: transparent; border: none;")
        top.addWidget(icon_lbl)
        layout.addLayout(top)

        self._value_lbl = QLabel("—")
        self._value_lbl.setObjectName("heading1")
        layout.addWidget(self._value_lbl)

        self._sub_lbl = QLabel("")
        self._sub_lbl.setObjectName("bodyMuted")
        self._sub_lbl.setStyleSheet(f"color: {C['on_surface_variant']}; font-size: 12px; border: none;")
        layout.addWidget(self._sub_lbl)

    def set_value(self, val: str, sub: str = "") -> None:
        self._value_lbl.setText(val)
        self._sub_lbl.setText(sub)


def _make_guide_card(icon: str, title: str, body: str, accent: str) -> QFrame:
    """Card dạng README cho từng mục hướng dẫn."""
    card = QFrame()
    card.setObjectName("card")
    lay = QHBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(14)

    icon_lbl = QLabel(icon)
    icon_lbl.setFixedSize(36, 36)
    icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_lbl.setStyleSheet(
        f"color: {accent}; font-size: 18px; background: transparent; border: none;"
    )
    lay.addWidget(icon_lbl)

    text = QVBoxLayout()
    text.setSpacing(3)
    t_lbl = QLabel(title)
    t_lbl.setStyleSheet(
        f"color: {accent}; font-size: 13px; font-weight: 700; background: transparent; border: none;"
    )
    text.addWidget(t_lbl)
    b_lbl = QLabel(body)
    b_lbl.setWordWrap(True)
    b_lbl.setStyleSheet(
        f"color: {C['on_surface_variant']}; font-size: 12px; background: transparent; border: none;"
    )
    text.addWidget(b_lbl)
    lay.addLayout(text)
    return card


class HomePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log_lines: list[str] = []
        self._setup_ui()
        self._start_metrics_timer()

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setStyleSheet(f"background: {C['background']};")
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(24)

        # ── Metrics row ───────────────────────────────────────────────────────
        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(12)

        self._cpu_card = _MetricCard("CPU Usage", "⚙", C["secondary_fixed_dim"])
        self._mem_card = _MetricCard("Memory Allocation", "💾", C["primary_fixed_dim"])
        self._latency_card = _MetricCard("Scanner Latency", "⚡", C["secondary_fixed_dim"])

        metrics_grid.addWidget(self._cpu_card, 0, 0)
        metrics_grid.addWidget(self._mem_card, 0, 1)
        metrics_grid.addWidget(self._latency_card, 0, 2)
        main_layout.addLayout(metrics_grid)

        # ── Two-column layout ─────────────────────────────────────────────────
        two_col = QHBoxLayout()
        two_col.setSpacing(24)

        # Left: README / hướng dẫn sử dụng
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        about_title = QLabel("QR Scan Studio")
        about_title.setObjectName("heading2")
        left_col.addWidget(about_title)

        about_desc = QLabel(
            "Hệ thống quét mã QR tích hợp Firebase Realtime Database, "
            "hỗ trợ xác thực bệnh nhân và tra cứu lịch hẹn tự động. "
            "Được xây dựng cho môi trường IoT với camera USB/webcam."
        )
        about_desc.setWordWrap(True)
        about_desc.setStyleSheet(
            f"color: {C['on_surface_variant']}; font-size: 12px; "
            f"border-left: 2px solid {C['primary']}; padding-left: 10px;"
        )
        left_col.addWidget(about_desc)

        guide_title = QLabel("Hướng dẫn sử dụng")
        guide_title.setObjectName("heading2")
        guide_title.setStyleSheet(
            f"color: {C['on_background']}; font-size: 14px; font-weight: 700; margin-top: 8px;"
        )
        left_col.addWidget(guide_title)

        left_col.addWidget(_make_guide_card(
            "🔑", "Bước 1 — Đăng nhập",
            "Nhập email và mật khẩu tài khoản Firebase. Tick \"Nhớ đăng nhập\" "
            "để tự điền lần sau. Nhấn Đăng nhập để xác thực.",
            C["primary"],
        ))
        left_col.addWidget(_make_guide_card(
            "📡", "Bước 2 — Kết nối Firebase",
            "Vào tab Firebase Config để kiểm tra và chỉnh sửa biến môi trường (.env). "
            "Đảm bảo API Key, Project ID, và file credentials đúng đường dẫn.",
            C["secondary"],
        ))
        left_col.addWidget(_make_guide_card(
            "📷", "Bước 3 — Thiết lập camera",
            "Vào tab Camera Setup để chọn camera, điều chỉnh ROI (vùng quét). "
            "Nhấn \"Configure ROI\" để khoanh vùng nhận diện mã QR chính xác hơn.",
            C["tertiary"],
        ))
        left_col.addWidget(_make_guide_card(
            "▶", "Bước 4 — Bắt đầu quét",
            "Vào tab Operation để khởi động luồng quét. Kết quả nhận diện bệnh nhân "
            "và lịch hẹn sẽ hiển thị trực tiếp trên màn hình và ghi vào Event Log.",
            C["secondary_fixed_dim"],
        ))
        left_col.addWidget(_make_guide_card(
            "📊", "Xem dữ liệu",
            "Tab Data Table hiển thị toàn bộ bệnh nhân và lịch hẹn từ Firebase. "
            "Dữ liệu tự động tải lại mỗi khi chuyển sang tab này.",
            C["outline"],
        ))
        left_col.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left_col)
        two_col.addWidget(left_widget, stretch=2)

        # Right: event log
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        log_header = QHBoxLayout()
        log_title = QLabel("Event Log")
        log_title.setObjectName("heading2")
        log_header.addWidget(log_title)
        log_header.addStretch()
        clear_btn = QPushButton("CLEAR")
        clear_btn.setObjectName("primaryAccent")
        clear_btn.setFlat(True)
        clear_btn.setStyleSheet(
            f"QPushButton {{ color: {C['primary']}; font-size: 11px; font-weight: 600; "
            f"font-family: 'JetBrains Mono', monospace; background: transparent; border: none; padding: 4px; }}"
            f"QPushButton:hover {{ color: {C['primary_container']}; }}"
        )
        clear_btn.clicked.connect(self._clear_log)
        log_header.addWidget(clear_btn)
        right_col.addLayout(log_header)

        self._log_area = QLabel()
        self._log_area.setObjectName("logArea")
        self._log_area.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._log_area.setWordWrap(True)
        self._log_area.setTextFormat(Qt.TextFormat.RichText)

        log_scroll = QScrollArea()
        log_scroll.setWidgetResizable(True)
        log_scroll.setFrameShape(QFrame.Shape.NoFrame)
        log_scroll.setObjectName("cardLowest")
        log_scroll.setStyleSheet(
            f"QScrollArea {{ background: {C['surface_container_lowest']}; "
            f"border: 1px solid rgba(66,71,84,0.5); border-radius: 8px; }}"
        )
        log_scroll.setWidget(self._log_area)
        log_scroll.setMinimumHeight(300)
        right_col.addWidget(log_scroll)

        right_widget = QWidget()
        right_widget.setLayout(right_col)
        two_col.addWidget(right_widget, stretch=1)

        main_layout.addLayout(two_col)
        main_layout.addStretch()

        scroll.setWidget(content)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

        self.log_line("[System] Khởi động QR Scan Studio.")

    def _start_metrics_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_metrics)
        self._timer.start(2000)
        self._update_metrics()

    def _update_metrics(self) -> None:
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            self._cpu_card.set_value(f"{cpu:.1f}%", "Optimal" if cpu < 70 else "High")
            used_gb = mem.used / (1024 ** 3)
            total_gb = mem.total / (1024 ** 3)
            self._mem_card.set_value(f"{used_gb:.1f} GB", f"/ {total_gb:.1f} GB")
        except Exception:
            pass
        self._latency_card.set_value("— ms", "SCANNER IDLE")

    @Slot(str)
    def log_line(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        color = C["secondary"] if msg.startswith("✓") or msg.startswith("[OK]") else \
                C["error"] if "Lỗi" in msg or "FAIL" in msg or "error" in msg.lower() else \
                C["tertiary"] if "WARN" in msg else C["on_surface_variant"]
        entry = (
            f'<span style="color:{C["outline"]}">[{ts}]</span> '
            f'<span style="color:{color}">{msg}</span><br>'
        )
        self._log_lines.append(entry)
        if len(self._log_lines) > 200:
            self._log_lines = self._log_lines[-200:]
        self._log_area.setText("".join(self._log_lines))

    def _clear_log(self) -> None:
        self._log_lines.clear()
        self._log_area.setText("")
