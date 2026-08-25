"""
Main application window — sidebar navigation + stacked content pages.
Layout ported from newUI/home.html / operation.html.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel,
    QPushButton, QStackedWidget, QSizePolicy, QSpacerItem, QScrollArea,
)

from config.theme import C


# ── Sidebar nav button ────────────────────────────────────────────────────────

class _NavButton(QPushButton):
    def __init__(self, icon: str, label: str, page_key: str, parent=None) -> None:
        super().__init__(f"  {icon}   {label}", parent)
        self.page_key = page_key
        self.setObjectName("navBtn")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setFont(QFont("Inter", 13))


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QWidget):
    """Shell: sidebar + top bar + stacked content pages."""

    logout_requested = Signal()
    theme_toggled = Signal()           # signal to AppController to rebuild UI
    log_message = Signal(str)          # propagated to home / operation pages

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: dict = {}
        self._nav_buttons: dict[str, _NavButton] = {}
        self._pages: dict[str, QWidget] = {}
        self._setup_ui()

    # ── Build shell ───────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_header())

        self._stack = QStackedWidget()
        right.addWidget(self._stack)

        right_widget = QWidget()
        right_widget.setLayout(right)
        root.addWidget(right_widget)

        self._build_pages()
        self._navigate("home")

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebarFrame")
        sidebar.setFixedWidth(280)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────────────
        header = QWidget()
        header.setStyleSheet(
            f"background: {C['surface_dim']}; border-bottom: 1px solid rgba(66,71,84,0.3);"
        )
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 16, 16, 16)
        h_layout.setSpacing(12)

        avatar = QFrame()
        avatar.setFixedSize(40, 40)
        avatar.setStyleSheet(
            f"background: {C['primary_container']}; border-radius: 20px;"
        )
        avatar_lbl = QLabel("👤")
        avatar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_lbl.setStyleSheet("font-size: 18px; background: transparent; border: none;")
        av_inner = QVBoxLayout(avatar)
        av_inner.setContentsMargins(0, 0, 0, 0)
        av_inner.addWidget(avatar_lbl)
        h_layout.addWidget(avatar)

        info = QVBoxLayout()
        info.setSpacing(2)
        self._user_lbl = QLabel("Operator Console")
        self._user_lbl.setStyleSheet(
            f"color: {C['primary']}; font-size: 14px; font-weight: 700; background: transparent; border: none;"
        )
        info.addWidget(self._user_lbl)
        ver_lbl = QLabel("V2.4.0-Stable")
        ver_lbl.setStyleSheet(
            f"color: {C['on_surface_variant']}; font-size: 11px; "
            f"font-family: 'JetBrains Mono', monospace; background: transparent; border: none;"
        )
        info.addWidget(ver_lbl)
        h_layout.addLayout(info)
        layout.addWidget(header)

        # ── Main nav items ────────────────────────────────────────────────────
        nav_area = QWidget()
        nav_layout = QVBoxLayout(nav_area)
        nav_layout.setContentsMargins(4, 8, 4, 8)
        nav_layout.setSpacing(2)

        for icon, label, key in [
            ("🏠", "Home",       "home"),
            ("🔥", "Firebase",   "firebase"),
            ("📊", "Data",       "data"),
            ("📷", "Camera",     "camera"),
            ("▶", "Operation",  "operation"),
        ]:
            btn = _NavButton(icon, label, key)
            btn.clicked.connect(lambda checked=False, k=key: self._navigate(k))
            self._nav_buttons[key] = btn
            nav_layout.addWidget(btn)

        layout.addWidget(nav_area)
        layout.addStretch()

        # ── Footer nav ────────────────────────────────────────────────────────
        footer_sep = QFrame()
        footer_sep.setFixedHeight(1)
        footer_sep.setStyleSheet(f"background: rgba(66,71,84,0.4); border: none;")
        layout.addWidget(footer_sep)

        footer_area = QWidget()
        f_layout = QVBoxLayout(footer_area)
        f_layout.setContentsMargins(4, 8, 4, 8)
        f_layout.setSpacing(2)

        # Theme toggle button
        from config.theme import get_theme_name
        theme_text = "☀️  Light mode" if get_theme_name() == "dark" else "🌙  Dark mode"
        self._theme_btn = QPushButton(f"  {theme_text}")
        self._theme_btn.setObjectName("themeToggleBtn")
        self._theme_btn.setMinimumHeight(36)
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        f_layout.addWidget(self._theme_btn)

        logout_btn = QPushButton("  🚪   Đăng xuất")
        logout_btn.setObjectName("navBtn")
        logout_btn.setMinimumHeight(40)
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-left: 2px solid transparent; "
            f"text-align: left; color: {C['error']}; padding: 9px 16px; font-size: 13px; }}"
            f"QPushButton:hover {{ background: rgba(147,0,10,0.15); }}"
        )
        logout_btn.clicked.connect(self.logout_requested.emit)
        f_layout.addWidget(logout_btn)
        layout.addWidget(footer_area)

        return sidebar

    def _build_header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("headerBar")
        bar.setFixedHeight(64)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 0, 24, 0)

        self._page_title_lbl = QLabel("QR Scanner Pro")
        self._page_title_lbl.setStyleSheet(
            f"color: {C['on_surface']}; font-size: 20px; font-weight: 700; background: transparent; border: none;"
        )
        layout.addWidget(self._page_title_lbl)
        layout.addStretch()

        # Status indicator
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(
            f"color: {C['secondary']}; font-size: 10px; background: transparent; border: none;"
        )
        layout.addWidget(self._status_dot)
        self._status_lbl = QLabel("ONLINE")
        self._status_lbl.setStyleSheet(
            f"color: {C['secondary']}; font-size: 11px; font-weight: 600; "
            f"font-family: 'JetBrains Mono', monospace; background: transparent; border: none;"
        )
        layout.addWidget(self._status_lbl)

        return bar

    def _build_pages(self) -> None:
        """Lazy-import pages to avoid circular imports."""
        from ui.pages.home_page import HomePage
        from ui.pages.firebase_page import FirebasePage
        from ui.pages.data_page import DataPage
        from ui.pages.camera_page import CameraPage
        from ui.pages.operation_page import OperationPage

        pages = {
            "home":      HomePage(),
            "firebase":  FirebasePage(),
            "data":      DataPage(),
            "camera":    CameraPage(),
            "operation": OperationPage(),
        }
        for key, page in pages.items():
            self._stack.addWidget(page)
            self._pages[key] = page

        # Cross-page log forwarding
        for page in pages.values():
            if hasattr(page, "log_line"):
                self.log_message.connect(page.log_line)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate(self, key: str) -> None:
        for k, btn in self._nav_buttons.items():
            btn.setChecked(k == key)
        if key in self._pages:
            self._stack.setCurrentWidget(self._pages[key])
        titles = {
            "home":      "QR Scanner Pro — Home",
            "firebase":  "Firebase Configuration",
            "data":      "Data Management",
            "camera":    "Camera Setup",
            "operation": "Operation Console",
        }
        self._page_title_lbl.setText(titles.get(key, "QR Scanner Pro"))

    # ── Session ───────────────────────────────────────────────────────────────

    def set_session(self, session: dict) -> None:
        self._session = session
        email = session.get("email", "Operator")
        display = email.split("@")[0] if "@" in email else email
        self._user_lbl.setText(display[:20])
        self._log_all(f"✓ Đã đăng nhập: {email}")

    def _log_all(self, msg: str) -> None:
        self.log_message.emit(msg)

    def log_line(self, msg: str) -> None:
        """Receive a log line and forward to all pages."""
        self.log_message.emit(msg)

    def shutdown_pages(self) -> None:
        for page in self._pages.values():
            shutdown = getattr(page, "shutdown", None)
            if callable(shutdown):
                shutdown()

    # ── Theme Toggle ──────────────────────────────────────────────────────────

    def _toggle_theme(self) -> None:
        """Switch between dark and light mode — signal controller to rebuild."""
        from config.theme import set_theme, get_theme_name

        current = get_theme_name()
        new_theme = "light" if current == "dark" else "dark"
        set_theme(new_theme)
        self.theme_toggled.emit()
