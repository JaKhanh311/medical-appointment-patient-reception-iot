"""
Firebase configuration page — ported from newUI/firebaseconfig.html.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QFileDialog,
)

from config.theme import C
from services.auth_service import read_env_file, write_env_file, IOT_DIR


class _FieldRow(QWidget):
    """Label + QLineEdit pair."""

    def __init__(self, label: str, placeholder: str = "", password: bool = False, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {C['on_surface_variant']}; font-size: 11px; font-weight: 600; "
            f"font-family: 'JetBrains Mono', monospace; background: transparent; border: none;"
        )
        layout.addWidget(lbl)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        if password:
            self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._edit)

    def text(self) -> str:
        return self._edit.text()

    def set_text(self, v: str) -> None:
        self._edit.setText(v)


class FirebasePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setStyleSheet(f"background: {C['background']};")
        main = QVBoxLayout(content)
        main.setContentsMargins(24, 24, 24, 24)
        main.setSpacing(24)

        # ── Page header ───────────────────────────────────────────────────────
        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("Firebase Configuration")
        title.setObjectName("heading1")
        header.addWidget(title)
        sub = QLabel("Quản lý xác thực và đường dẫn Firebase Realtime Database.")
        sub.setObjectName("bodyMuted")
        header.addWidget(sub)
        main.addLayout(header)

        # ── Status badge ──────────────────────────────────────────────────────
        badge_row = QHBoxLayout()
        self._conn_badge = QLabel("● CONNECTED")
        self._conn_badge.setStyleSheet(
            f"color: {C['secondary_fixed']}; font-size: 11px; font-weight: 600; "
            f"font-family: 'JetBrains Mono', monospace; background: transparent; border: none;"
        )
        badge_row.addWidget(self._conn_badge)
        badge_row.addStretch()
        main.addLayout(badge_row)

        # ── Credentials service-account key ──────────────────────────────────
        cred_card = QFrame()
        cred_card.setObjectName("card")
        cred_layout = QVBoxLayout(cred_card)
        cred_layout.setContentsMargins(20, 20, 20, 20)
        cred_layout.setSpacing(16)

        cred_title = QLabel("Service Account Key")
        cred_title.setObjectName("heading2")
        cred_layout.addWidget(cred_title)

        cred_desc = QLabel(
            "Đường dẫn tới file JSON service account (firebase-key.json). "
            "Cần để khởi tạo firebase-admin SDK."
        )
        cred_desc.setObjectName("bodyMuted")
        cred_desc.setWordWrap(True)
        cred_layout.addWidget(cred_desc)

        cred_row = QHBoxLayout()
        self._cred_field = _FieldRow("FIREBASE_CRED_JSON", "path/to/firebase-key.json")
        cred_row.addWidget(self._cred_field)
        browse_btn = QPushButton("Browse…")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_cred)
        cred_row.addWidget(browse_btn)
        cred_layout.addLayout(cred_row)
        main.addWidget(cred_card)

        # ── Database URL ──────────────────────────────────────────────────────
        db_card = QFrame()
        db_card.setObjectName("card")
        db_layout = QVBoxLayout(db_card)
        db_layout.setContentsMargins(20, 20, 20, 20)
        db_layout.setSpacing(16)

        db_title = QLabel("Database URL")
        db_title.setObjectName("heading2")
        db_layout.addWidget(db_title)

        self._db_field = _FieldRow(
            "FIREBASE_DB_URL", "https://your-project-default-rtdb.firebaseio.com"
        )
        db_layout.addWidget(self._db_field)
        main.addWidget(db_card)

        # ── AES Key ───────────────────────────────────────────────────────────
        aes_card = QFrame()
        aes_card.setObjectName("card")
        aes_layout = QVBoxLayout(aes_card)
        aes_layout.setContentsMargins(20, 20, 20, 20)
        aes_layout.setSpacing(16)

        aes_title = QLabel("AES-256-GCM Key")
        aes_title.setObjectName("heading2")
        aes_layout.addWidget(aes_title)

        aes_desc = QLabel(
            "Khóa AES-GCM base64 để giải mã payload QR. "
            "Có thể thêm nhiều khóa phụ trong AES_GCM_ALT_KEYS_B64 (phân cách bởi dấu phẩy)."
        )
        aes_desc.setObjectName("bodyMuted")
        aes_desc.setWordWrap(True)
        aes_layout.addWidget(aes_desc)

        self._aes_field = _FieldRow("AES_GCM_KEY_B64", "base64-encoded-32-byte-key", password=True)
        aes_layout.addWidget(self._aes_field)

        self._alt_keys_field = _FieldRow("AES_GCM_ALT_KEYS_B64", "key2_b64,key3_b64 (tùy chọn)")
        aes_layout.addWidget(self._alt_keys_field)
        main.addWidget(aes_card)

        # ── Save button ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("  💾  Lưu cấu hình")
        save_btn.setObjectName("primaryBtn")
        save_btn.setFixedHeight(40)
        save_btn.clicked.connect(self._save_values)
        btn_row.addWidget(save_btn)
        main.addLayout(btn_row)

        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("bodyMuted")
        main.addWidget(self._status_lbl)

        main.addStretch()
        scroll.setWidget(content)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _load_values(self) -> None:
        env = read_env_file()
        self._cred_field.set_text(env.get("FIREBASE_CRED_JSON", ""))
        self._db_field.set_text(env.get("FIREBASE_DB_URL", ""))
        self._aes_field.set_text(env.get("AES_GCM_KEY_B64", ""))
        self._alt_keys_field.set_text(env.get("AES_GCM_ALT_KEYS_B64", ""))

    def _browse_cred(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn Firebase service account key", str(IOT_DIR), "JSON files (*.json)"
        )
        if path:
            self._cred_field.set_text(path)

    def _save_values(self) -> None:
        updates: dict[str, str] = {}
        cred = self._cred_field.text().strip()
        db_url = self._db_field.text().strip()
        aes = self._aes_field.text().strip()
        alt = self._alt_keys_field.text().strip()

        if cred:
            updates["FIREBASE_CRED_JSON"] = cred
        if db_url:
            updates["FIREBASE_DB_URL"] = db_url
        if aes:
            updates["AES_GCM_KEY_B64"] = aes
        if alt:
            updates["AES_GCM_ALT_KEYS_B64"] = alt

        try:
            write_env_file(updates)
            self._status_lbl.setText("✓ Đã lưu thành công vào file .env")
            self._status_lbl.setStyleSheet(
                f"color: {C['secondary']}; font-size: 12px; background: transparent; border: none;"
            )
        except Exception as exc:
            self._status_lbl.setText(f"Lỗi: {exc}")
            self._status_lbl.setStyleSheet(
                f"color: {C['error']}; font-size: 12px; background: transparent; border: none;"
            )

    @Slot(str)
    def log_line(self, _msg: str) -> None:
        pass  # firebase page doesn't display logs
