"""
Login page — Material Design 3, ported from newUI/login.html.
Login logic ported from qr_scan_gui.py (_firebase_sign_in, settings).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRunnable, QThreadPool, QObject, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QFrame, QSizePolicy, QSpacerItem,
)

from config.theme import C
from services.auth_service import firebase_sign_in, load_settings, save_settings


# ── Login worker (runs in thread pool) ───────────────────────────────────────

class _LoginSignals(QObject):
    success = Signal(dict)
    failure = Signal(str)


class _LoginWorker(QRunnable):
    def __init__(self, email: str, password: str) -> None:
        super().__init__()
        self.email = email
        self.password = password
        self.signals = _LoginSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = firebase_sign_in(self.email, self.password)
            self.signals.success.emit(result)
        except Exception as exc:
            self.signals.failure.emit(str(exc))


# ── Input field widget ────────────────────────────────────────────────────────

class _InputField(QFrame):
    """Single input row: label above, icon + QLineEdit inside a bordered frame."""

    def __init__(
        self,
        label: str,
        placeholder: str = "",
        is_password: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_password = is_password
        self._pw_visible = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Label
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {C['on_surface_variant']}; font-size: 11px; font-weight: 600;")
        outer.addWidget(lbl)

        # Input border frame
        self._border = QFrame()
        self._border.setStyleSheet(
            f"QFrame {{ background: {C['surface_container_lowest']}; "
            f"border: 1px solid {C['outline_variant']}; border-radius: 4px; }}"
        )
        border_layout = QHBoxLayout(self._border)
        border_layout.setContentsMargins(12, 0, 8, 0)
        border_layout.setSpacing(8)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setStyleSheet(
            "QLineEdit { background: transparent; border: none; "
            f"color: {C['on_surface']}; font-size: 13px; padding: 10px 0; "
            "font-family: 'JetBrains Mono', monospace; }"
        )
        if is_password:
            self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        border_layout.addWidget(self._edit)

        if is_password:
            self._vis_btn = QPushButton("👁")
            self._vis_btn.setFixedSize(30, 30)
            self._vis_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; "
                f"color: {C['outline']}; font-size: 14px; }}"
                f"QPushButton:hover {{ color: {C['on_surface_variant']}; }}"
            )
            self._vis_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._vis_btn.clicked.connect(self._toggle_visibility)
            border_layout.addWidget(self._vis_btn)

        outer.addWidget(self._border)

        # Focus highlight
        self._edit.focusInEvent = self._on_focus_in
        self._edit.focusOutEvent = self._on_focus_out

    def _on_focus_in(self, event) -> None:
        self._border.setStyleSheet(
            f"QFrame {{ background: {C['surface_container_lowest']}; "
            f"border: 1px solid {C['primary']}; border-radius: 4px; }}"
        )
        QLineEdit.focusInEvent(self._edit, event)

    def _on_focus_out(self, event) -> None:
        self._border.setStyleSheet(
            f"QFrame {{ background: {C['surface_container_lowest']}; "
            f"border: 1px solid {C['outline_variant']}; border-radius: 4px; }}"
        )
        QLineEdit.focusOutEvent(self._edit, event)

    def _toggle_visibility(self) -> None:
        self._pw_visible = not self._pw_visible
        self._edit.setEchoMode(
            QLineEdit.EchoMode.Normal if self._pw_visible else QLineEdit.EchoMode.Password
        )
        self._vis_btn.setText("🙈" if self._pw_visible else "👁")

    def text(self) -> str:
        return self._edit.text()

    def set_text(self, value: str) -> None:
        self._edit.setText(value)

    def line_edit(self) -> QLineEdit:
        return self._edit


# ── Login Page ────────────────────────────────────────────────────────────────

class LoginPage(QWidget):
    """Full-screen login page matching newUI/login.html design."""

    login_success = Signal(dict)   # emitted on successful Firebase auth
    theme_toggled = Signal()       # emitted when user toggles dark/light mode

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = load_settings()
        self._pool = QThreadPool.globalInstance()
        self._setup_ui()
        self._prefill_saved_credentials()

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"QWidget {{ background-color: {C['login_bg']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Theme toggle button — top right corner
        from config.theme import get_theme_name
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(16, 12, 16, 0)
        top_bar.addStretch()
        theme_text = "☀️  Light mode" if get_theme_name() == "dark" else "🌙  Dark mode"
        self._theme_btn = QPushButton(theme_text)
        self._theme_btn.setObjectName("themeToggleBtn")
        self._theme_btn.setFixedWidth(140)
        self._theme_btn.setMinimumHeight(32)
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._on_toggle_theme)
        top_bar.addWidget(self._theme_btn)
        root.addLayout(top_bar)

        # Stretch ratio 20:80 → đẩy nội dung lên cao hơn
        root.addStretch(2)

        # ── Center column ────────────────────────────────────────────────────
        center = QWidget()
        center.setFixedWidth(448)
        col = QVBoxLayout(center)
        col.setContentsMargins(0, 48, 0, 48)
        col.setSpacing(32)

        # Logo
        logo_block = QWidget()
        logo_col = QVBoxLayout(logo_block)
        logo_col.setContentsMargins(0, 0, 0, 0)
        logo_col.setSpacing(8)
        logo_col.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel("⬡")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"color: {C['primary']}; font-size: 48px;")
        logo_col.addWidget(icon_lbl)

        title_lbl = QLabel("QR Scan Studio")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet(
            f"color: {C['on_background']}; font-size: 28px; font-weight: 700; letter-spacing: -0.5px;"
        )
        logo_col.addWidget(title_lbl)
        col.addWidget(logo_block)

        # Login card
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {C['surface_container_high']}; "
            f"border: 1px solid {C['outline_variant']}; border-radius: 12px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(20)

        # Card header
        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        icon_box = QFrame()
        icon_box.setFixedSize(48, 48)
        icon_box.setStyleSheet(
            f"QFrame {{ background: {C['surface_container_lowest']}; "
            f"border: 1px solid {C['outline_variant']}; border-radius: 8px; }}"
        )
        icon_box_layout = QVBoxLayout(icon_box)
        icon_box_layout.setContentsMargins(0, 0, 0, 0)
        shield_lbl = QLabel("🛡")
        shield_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shield_lbl.setStyleSheet(f"border: none; background: transparent; font-size: 22px;")
        icon_box_layout.addWidget(shield_lbl)
        header_row.addWidget(icon_box)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        login_title = QLabel("Đăng nhập hệ thống")
        login_title.setStyleSheet(
            f"color: {C['on_surface']}; font-size: 18px; font-weight: 600; border: none;"
        )
        header_text.addWidget(login_title)
        login_sub = QLabel("Xác thực tài khoản Firebase để truy cập.")
        login_sub.setStyleSheet(
            f"color: {C['on_surface_variant']}; font-size: 13px; border: none;"
        )
        header_text.addWidget(login_sub)
        header_row.addLayout(header_text)
        card_layout.addLayout(header_row)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {C['outline_variant']}; border: none;")
        card_layout.addWidget(sep)

        # Email input
        self._email_field = _InputField("Email Firebase", "admin@domain.com")
        card_layout.addWidget(self._email_field)

        # Password input
        self._pw_field = _InputField("Mật khẩu", "••••••••", is_password=True)
        self._pw_field.line_edit().returnPressed.connect(self._do_login)
        card_layout.addWidget(self._pw_field)

        # Remember checkbox
        self._remember_cb = QCheckBox("Lưu phiên đăng nhập cục bộ")
        self._remember_cb.setStyleSheet(
            f"QCheckBox {{ color: {C['on_surface']}; font-size: 13px; border: none; }}"
            f"QCheckBox::indicator {{ width: 16px; height: 16px; "
            f"border: 1px solid {C['outline_variant']}; border-radius: 2px; "
            f"background: {C['surface_container_lowest']}; }}"
            f"QCheckBox::indicator:checked {{ background: {C['primary']}; border-color: {C['primary']}; }}"
        )
        saved_remember = bool(self._settings.get("auth", {}).get("remember_login", False))
        self._remember_cb.setChecked(saved_remember)
        card_layout.addWidget(self._remember_cb)

        # Login button — explicit high-contrast style for both themes
        self._login_btn = QPushButton("Kết nối tới Console  →")
        self._login_btn.setObjectName("primaryBtn")
        self._login_btn.setMinimumHeight(44)
        self._login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._login_btn.setStyleSheet(
            f"QPushButton {{ background: {C['primary']}; color: {C['on_primary']}; "
            f"border: none; border-radius: 6px; padding: 12px 24px; "
            f"font-size: 14px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {C['primary_container']}; color: {C['on_primary']}; }}"
            f"QPushButton:pressed {{ background: {C['primary_container']}; color: {C['on_primary']}; }}"
        )
        self._login_btn.clicked.connect(self._do_login)
        card_layout.addWidget(self._login_btn)

        # Error label
        self._error_lbl = QLabel("")
        self._error_lbl.setObjectName("errorLabel")
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setStyleSheet(
            f"color: {C['error']}; font-size: 12px; border: none;"
        )
        self._error_lbl.hide()
        card_layout.addWidget(self._error_lbl)

        # Footer
        footer_sep = QFrame()
        footer_sep.setFixedHeight(1)
        footer_sep.setStyleSheet(f"background: {C['outline_variant']}; border: none;")
        card_layout.addWidget(footer_sep)

        footer_lbl = QLabel("🔐  Bảo vệ bởi Firebase Authentication")
        footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_lbl.setStyleSheet(
            f"color: {C['on_surface_variant']}; font-size: 11px; "
            f"font-family: 'JetBrains Mono', monospace; border: none;"
        )
        card_layout.addWidget(footer_lbl)

        col.addWidget(card)
        root.addWidget(center, alignment=Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(18)

    # ── Logic ────────────────────────────────────────────────────────────────

    def _on_toggle_theme(self) -> None:
        """Toggle dark/light mode and signal controller to rebuild UI."""
        from config.theme import set_theme, get_theme_name
        current = get_theme_name()
        new_theme = "light" if current == "dark" else "dark"
        set_theme(new_theme)
        self.theme_toggled.emit()

    def _prefill_saved_credentials(self) -> None:
        auth = self._settings.get("auth", {})
        if not auth.get("remember_login"):
            return
        email = str(auth.get("email", ""))
        password = str(auth.get("password", ""))
        if email:
            self._email_field.set_text(email)
        if password:
            self._pw_field.set_text(password)

    def _do_login(self) -> None:
        email = self._email_field.text().strip()
        password = self._pw_field.text().strip()
        if not email or not password:
            self._show_error("Vui lòng nhập email và mật khẩu.")
            return

        self._login_btn.setEnabled(False)
        self._login_btn.setText("Đang đăng nhập…")
        self._error_lbl.hide()

        worker = _LoginWorker(email, password)
        worker.signals.success.connect(self._on_login_success)
        worker.signals.failure.connect(self._on_login_failure)
        self._pool.start(worker)

    @Slot(dict)
    def _on_login_success(self, session: dict) -> None:
        email = self._email_field.text().strip()
        password = self._pw_field.text().strip()
        remember = self._remember_cb.isChecked()
        self._settings.setdefault("auth", {})["remember_login"] = remember
        self._settings["auth"]["email"] = email if remember else ""
        self._settings["auth"]["password"] = password if remember else ""
        save_settings(self._settings)

        self._login_btn.setEnabled(True)
        self._login_btn.setText("Kết nối tới Console  →")
        self.login_success.emit(session)

    @Slot(str)
    def _on_login_failure(self, message: str) -> None:
        self._login_btn.setEnabled(True)
        self._login_btn.setText("Kết nối tới Console  →")
        self._show_error(f"Lỗi: {message}")

    def _show_error(self, msg: str) -> None:
        self._error_lbl.setText(msg)
        self._error_lbl.show()
