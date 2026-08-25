"""
QR Code Generator — Mô phỏng đặt lịch hẹn và xuất mã QR.
Dùng khi không có ứng dụng di động Android.

Chạy: python qr_generator_gui.py
Yêu cầu: PySide6, qrcode, Pillow, firebase-admin, cryptography, python-dotenv
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

# ── Path setup ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, db as firebase_db

# Initialize Firebase
_cred_files = sorted(BASE_DIR.glob("*firebase-adminsdk*.json"))
if not _cred_files:
    print("ERROR: Không tìm thấy file firebase-adminsdk*.json")
    sys.exit(1)

_cred = credentials.Certificate(str(_cred_files[0]))
_sa_data = json.loads(_cred_files[0].read_text(encoding="utf-8"))
_project_id = _sa_data.get("project_id", "")
_db_url = f"https://{_project_id}-default-rtdb.firebaseio.com"

if not firebase_admin._apps:
    firebase_admin.initialize_app(_cred, {"databaseURL": _db_url})


def _get_aes_key() -> bytes:
    key_b64 = os.environ.get("AES_GCM_KEY_B64", "").strip()
    if not key_b64:
        raise RuntimeError("Thiếu AES_GCM_KEY_B64 trong file .env")
    return base64.b64decode(key_b64)


def encrypt_appointment_id(appointment_id: str) -> str:
    """Encrypt appointment_id → QR payload format: v1:<base64(nonce + ciphertext)>"""
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, appointment_id.encode("utf-8"), None)
    raw = nonce + ct
    return "v1:" + base64.b64encode(raw).decode("utf-8")


# ── PySide6 GUI ──────────────────────────────────────────────────────────────
from PySide6.QtCore import Qt, Slot, QThread, Signal, QObject, QSortFilterProxyModel
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QDateEdit, QFrame,
    QMessageBox, QFileDialog, QScrollArea, QGridLayout, QGroupBox,
    QCompleter,
)

import qrcode
from PIL import Image as PILImage
from io import BytesIO


class FirebaseWorker(QObject):
    """Load data from Firebase in background thread."""
    patients_loaded = Signal(list)
    doctors_loaded = Signal(list)
    specialties_loaded = Signal(list)
    appointment_created = Signal(str)  # appointment_id
    error = Signal(str)

    def load_patients(self):
        try:
            data = firebase_db.reference("patients").get() or {}
            patients = []
            for pid, info in data.items():
                if isinstance(info, dict):
                    patients.append({
                        "id": pid,
                        "name": info.get("name", "N/A"),
                        "phone": info.get("phone", ""),
                    })
            patients.sort(key=lambda x: x["name"])
            self.patients_loaded.emit(patients)
        except Exception as e:
            self.error.emit(f"Lỗi tải bệnh nhân: {e}")

    def load_doctors(self):
        try:
            data = firebase_db.reference("doctors").get() or {}
            doctors = []
            for did, info in data.items():
                if isinstance(info, dict):
                    doctors.append({
                        "id": did,
                        "name": info.get("name", "N/A"),
                        "specialtyID": info.get("specialtyID", ""),
                    })
            doctors.sort(key=lambda x: x["name"])
            self.doctors_loaded.emit(doctors)
        except Exception as e:
            self.error.emit(f"Lỗi tải bác sĩ: {e}")

    def load_specialties(self):
        try:
            data = firebase_db.reference("specialties").get() or {}
            specs = []
            for sid, info in data.items():
                if isinstance(info, dict):
                    specs.append({"id": sid, "name": info.get("name", sid)})
                else:
                    specs.append({"id": sid, "name": str(info)})
            specs.sort(key=lambda x: x["name"])
            self.specialties_loaded.emit(specs)
        except Exception as e:
            self.error.emit(f"Lỗi tải chuyên khoa: {e}")

    def create_appointment(self, doctor_id: str, patient_id: str, specialty_id: str,
                           appt_date: str, session: str, patient_name: str):
        try:
            # Generate appointment ID
            ts = int(time.time() * 1000)
            appt_id = f"appt_{ts}"

            # Build appointment data matching Firebase structure
            appt_data = {
                "appointmentID": appt_id,
                "patientID": patient_id,
                "patientName": patient_name,
                "doctorID": doctor_id,
                "specialtyID": specialty_id,
                "date": appt_date,
                "session": session,
                "status": "scheduled",
                "createdAt": ts,
                "checkedIn": False,
            }

            # Write to appointment_new/{doctorID}/{date}/{appointmentID}
            ref_path = f"appointment_new/{doctor_id}/{appt_date}/{appt_id}"
            firebase_db.reference(ref_path).set(appt_data)

            self.appointment_created.emit(appt_id)
        except Exception as e:
            self.error.emit(f"Lỗi tạo lịch hẹn: {e}")


class QRGeneratorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QR Generator — Mô phỏng đặt lịch hẹn")
        self.setMinimumSize(800, 700)
        self.resize(900, 750)

        self._patients: list[dict] = []
        self._doctors: list[dict] = []
        self._specialties: list[dict] = []
        self._last_qr_pixmap: QPixmap | None = None

        self._worker = FirebaseWorker()
        self._worker.patients_loaded.connect(self._on_patients_loaded)
        self._worker.doctors_loaded.connect(self._on_doctors_loaded)
        self._worker.specialties_loaded.connect(self._on_specialties_loaded)
        self._worker.appointment_created.connect(self._on_appointment_created)
        self._worker.error.connect(self._on_error)

        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Title
        title = QLabel("🏥  Mô phỏng đặt lịch hẹn & Xuất mã QR")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a73e8;")
        main_layout.addWidget(title)

        desc = QLabel("Công cụ này thay thế ứng dụng di động để tạo lịch hẹn và xuất mã QR cho demo.")
        desc.setStyleSheet("font-size: 13px; color: #555;")
        desc.setWordWrap(True)
        main_layout.addWidget(desc)

        # ── Form ─────────────────────────────────────────────────────────────
        form_group = QGroupBox("Thông tin lịch hẹn")
        form_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 14px; }")
        form_layout = QGridLayout(form_group)
        form_layout.setSpacing(12)

        # Patient
        form_layout.addWidget(QLabel("Bệnh nhân:"), 0, 0)
        self._patient_combo = QComboBox()
        self._patient_combo.setMinimumWidth(300)
        self._patient_combo.setEditable(True)
        self._patient_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._patient_combo.setPlaceholderText("Gõ tên để tìm kiếm...")
        form_layout.addWidget(self._patient_combo, 0, 1)

        # Doctor
        form_layout.addWidget(QLabel("Bác sĩ:"), 1, 0)
        self._doctor_combo = QComboBox()
        self._doctor_combo.setMinimumWidth(300)
        self._doctor_combo.setEditable(True)
        self._doctor_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._doctor_combo.setPlaceholderText("Gõ tên để tìm kiếm...")
        form_layout.addWidget(self._doctor_combo, 1, 1)

        # Specialty
        form_layout.addWidget(QLabel("Chuyên khoa:"), 2, 0)
        self._specialty_combo = QComboBox()
        self._specialty_combo.setMinimumWidth(300)
        self._specialty_combo.setPlaceholderText("Đang tải...")
        form_layout.addWidget(self._specialty_combo, 2, 1)

        # Date
        form_layout.addWidget(QLabel("Ngày hẹn:"), 3, 0)
        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(date.today())
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        form_layout.addWidget(self._date_edit, 3, 1)

        # Session
        form_layout.addWidget(QLabel("Buổi:"), 4, 0)
        self._session_combo = QComboBox()
        self._session_combo.addItems(["morning", "afternoon"])
        form_layout.addWidget(self._session_combo, 4, 1)

        main_layout.addWidget(form_group)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._create_btn = QPushButton("📋  Tạo lịch hẹn + Xuất QR")
        self._create_btn.setMinimumHeight(44)
        self._create_btn.setStyleSheet(
            "QPushButton { background: #1a73e8; color: white; border: none; "
            "border-radius: 8px; font-size: 14px; font-weight: bold; padding: 12px 24px; }"
            "QPushButton:hover { background: #1565c0; }"
            "QPushButton:disabled { background: #ccc; }"
        )
        self._create_btn.clicked.connect(self._on_create_clicked)
        btn_row.addWidget(self._create_btn)

        self._save_btn = QPushButton("💾  Lưu QR thành file")
        self._save_btn.setMinimumHeight(44)
        self._save_btn.setStyleSheet(
            "QPushButton { background: #00897b; color: white; border: none; "
            "border-radius: 8px; font-size: 14px; font-weight: bold; padding: 12px 24px; }"
            "QPushButton:hover { background: #00695c; }"
            "QPushButton:disabled { background: #ccc; }"
        )
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save_clicked)
        btn_row.addWidget(self._save_btn)

        self._refresh_btn = QPushButton("🔄  Tải lại dữ liệu")
        self._refresh_btn.setMinimumHeight(44)
        self._refresh_btn.setStyleSheet(
            "QPushButton { background: #f5f5f5; color: #333; border: 1px solid #ddd; "
            "border-radius: 8px; font-size: 13px; padding: 12px 16px; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        self._refresh_btn.clicked.connect(self._load_data)
        btn_row.addWidget(self._refresh_btn)

        main_layout.addLayout(btn_row)

        # ── QR Display ────────────────────────────────────────────────────────
        qr_group = QGroupBox("Mã QR")
        qr_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 14px; }")
        qr_layout = QVBoxLayout(qr_group)

        self._qr_label = QLabel("Chưa tạo mã QR")
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setMinimumSize(300, 300)
        self._qr_label.setStyleSheet(
            "background: white; border: 2px dashed #ccc; border-radius: 12px; "
            "font-size: 14px; color: #999;"
        )
        qr_layout.addWidget(self._qr_label)

        self._info_label = QLabel("")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_label.setStyleSheet("font-size: 12px; color: #666;")
        self._info_label.setWordWrap(True)
        qr_layout.addWidget(self._info_label)

        main_layout.addWidget(qr_group)

        # Status bar
        self._status = QLabel("Sẵn sàng")
        self._status.setStyleSheet("font-size: 11px; color: #888; padding: 4px;")
        main_layout.addWidget(self._status)

    def _load_data(self):
        self._status.setText("Đang tải dữ liệu từ Firebase...")
        self._worker.load_patients()
        self._worker.load_doctors()
        self._worker.load_specialties()

    @Slot(list)
    def _on_patients_loaded(self, patients: list):
        self._patients = patients
        self._patient_combo.clear()
        for p in patients:
            self._patient_combo.addItem(f"{p['name']} ({p['id']})", p["id"])
        # Enable search/filter by name
        completer = self._patient_combo.completer()
        if completer:
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._status.setText(f"Đã tải {len(patients)} bệnh nhân")

    @Slot(list)
    def _on_doctors_loaded(self, doctors: list):
        self._doctors = doctors
        self._doctor_combo.clear()
        for d in doctors:
            self._doctor_combo.addItem(f"{d['name']} ({d['id']})", d["id"])
        # Enable search/filter by name
        completer = self._doctor_combo.completer()
        if completer:
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)

    @Slot(list)
    def _on_specialties_loaded(self, specs: list):
        self._specialties = specs
        self._specialty_combo.clear()
        for s in specs:
            self._specialty_combo.addItem(f"{s['name']}", s["id"])

    @Slot(str)
    def _on_appointment_created(self, appt_id: str):
        self._status.setText(f"✓ Đã tạo lịch hẹn: {appt_id}")
        self._generate_qr(appt_id)

    @Slot(str)
    def _on_error(self, msg: str):
        self._status.setText(f"❌ {msg}")
        QMessageBox.warning(self, "Lỗi", msg)

    def _on_create_clicked(self):
        patient_idx = self._patient_combo.currentIndex()
        doctor_idx = self._doctor_combo.currentIndex()
        specialty_idx = self._specialty_combo.currentIndex()

        if patient_idx < 0 or not self._patients:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng chọn bệnh nhân.")
            return
        if doctor_idx < 0 or not self._doctors:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng chọn bác sĩ.")
            return

        patient = self._patients[patient_idx]
        doctor = self._doctors[doctor_idx]
        specialty_id = self._specialty_combo.currentData() or ""
        appt_date = self._date_edit.date().toString("yyyy-MM-dd")
        session = self._session_combo.currentText()

        self._create_btn.setEnabled(False)
        self._status.setText("Đang tạo lịch hẹn...")

        self._worker.create_appointment(
            doctor_id=doctor["id"],
            patient_id=patient["id"],
            specialty_id=specialty_id,
            appt_date=appt_date,
            session=session,
            patient_name=patient["name"],
        )
        self._create_btn.setEnabled(True)

    def _generate_qr(self, appointment_id: str):
        try:
            payload = encrypt_appointment_id(appointment_id)
            # Generate QR image
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
            qr.add_data(payload)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            # Convert PIL → QPixmap
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            qimage = QImage.fromData(buffer.read())
            pixmap = QPixmap.fromImage(qimage)

            self._last_qr_pixmap = pixmap
            self._qr_label.setPixmap(pixmap.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self._save_btn.setEnabled(True)

            self._info_label.setText(
                f"Appointment ID: {appointment_id}\n"
                f"Payload (encrypted): {payload[:40]}...\n"
                f"Đưa mã QR này vào camera IoT để quét check-in."
            )
        except Exception as e:
            self._on_error(f"Lỗi tạo QR: {e}")

    def _on_save_clicked(self):
        if not self._last_qr_pixmap:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu mã QR", f"qr_appointment_{int(time.time())}.png", "PNG Files (*.png)"
        )
        if path:
            self._last_qr_pixmap.save(path)
            self._status.setText(f"✓ Đã lưu: {path}")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = QRGeneratorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
