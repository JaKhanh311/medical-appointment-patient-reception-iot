"""
AppController — top-level QMainWindow that manages Login ↔ MainWindow transitions.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QStackedWidget

from ui.pages.login_page import LoginPage
from ui.main_window import MainWindow


class AppController(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("QR Scan Studio")
        self.resize(1400, 860)
        self.setMinimumSize(1100, 720)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._session: dict = {}
        self._build_login()
        self._build_main()
        self._stack.setCurrentWidget(self._login_page)

    def _build_login(self) -> None:
        self._login_page = LoginPage()
        self._login_page.login_success.connect(self._on_login_success)
        self._login_page.theme_toggled.connect(self._on_theme_toggled)
        self._stack.addWidget(self._login_page)

    def _build_main(self) -> None:
        self._main_window = MainWindow()
        self._main_window.logout_requested.connect(self._on_logout)
        self._main_window.theme_toggled.connect(self._on_theme_toggled)
        self._stack.addWidget(self._main_window)

    def _on_login_success(self, session: dict) -> None:
        self._session = session
        self._main_window.set_session(session)
        self._stack.setCurrentWidget(self._main_window)

    def _on_logout(self) -> None:
        self._main_window.shutdown_pages()
        self._session = {}
        self._stack.setCurrentWidget(self._login_page)

    def _on_theme_toggled(self) -> None:
        """Rebuild entire UI after theme change."""
        self._apply_theme_and_rebuild()

    def _apply_theme_and_rebuild(self) -> None:
        """Apply new QSS and rebuild all widgets to pick up new colors."""
        from config.theme import build_qss
        from PySide6.QtWidgets import QApplication

        qapp = QApplication.instance()
        if qapp:
            qapp.setStyleSheet(build_qss())

        # Determine which screen to show after rebuild
        was_logged_in = bool(self._session)

        # Destroy old widgets
        old_login = self._login_page
        old_main = self._main_window
        self._stack.removeWidget(old_login)
        self._stack.removeWidget(old_main)
        old_main.shutdown_pages()
        old_login.deleteLater()
        old_main.deleteLater()

        # Rebuild
        self._build_login()
        self._build_main()

        if was_logged_in:
            self._main_window.set_session(self._session)
            self._stack.setCurrentWidget(self._main_window)
        else:
            self._stack.setCurrentWidget(self._login_page)

    def closeEvent(self, event) -> None:
        self._main_window.shutdown_pages()
        super().closeEvent(event)
