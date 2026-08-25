"""
Data management page — ported from newUI/data_manager.html.
Displays patients and appointments from Firebase.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QRunnable, QThreadPool, QObject, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QComboBox, QLineEdit, QSizePolicy,
)

from config.theme import C

# Add IoT directory to path so firebase_conn can be imported
_IOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_IOT_DIR) not in sys.path:
    sys.path.insert(0, str(_IOT_DIR))


class _FetchSignals(QObject):
    done = Signal(list, str)   # (rows, error_msg)


class _FetchWorker(QRunnable):
    def __init__(self, collection: str) -> None:
        super().__init__()
        self.collection = collection
        self.signals = _FetchSignals()

    def run(self) -> None:
        try:
            from firebase_conn import get_db_ref
            ref = get_db_ref(self.collection)
            data = ref.get()
            rows: list[dict] = []
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        row = {"id": k}
                        row.update(v)
                        rows.append(row)
                    else:
                        rows.append({"id": k, "value": str(v)})
            self.signals.done.emit(rows, "")
        except Exception as exc:
            self.signals.done.emit([], str(exc))


class DataPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._setup_ui()

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setStyleSheet(f"background: {C['background']};")
        main = QVBoxLayout(content)
        main.setContentsMargins(24, 24, 24, 24)
        main.setSpacing(20)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel("Data Management")
        title.setObjectName("heading1")
        title_col.addWidget(title)
        sub = QLabel("Xem và tìm kiếm dữ liệu từ Firebase Realtime Database.")
        sub.setObjectName("bodyMuted")
        title_col.addWidget(sub)
        hdr.addLayout(title_col)
        hdr.addStretch()
        main.addLayout(hdr)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        self._collection_combo = QComboBox()
        self._collection_combo.addItems(["patients", "appointments", "doctors", "queue"])
        self._collection_combo.setFixedWidth(180)
        toolbar.addWidget(self._collection_combo)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Tìm kiếm theo ID hoặc giá trị…")
        self._search_edit.textChanged.connect(self._filter_table)
        toolbar.addWidget(self._search_edit)

        refresh_btn = QPushButton("🔄  Tải dữ liệu")
        refresh_btn.setObjectName("primaryBtn")
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(self._fetch_data)
        toolbar.addWidget(refresh_btn)
        main.addLayout(toolbar)

        # ── Status ────────────────────────────────────────────────────────────
        self._status_lbl = QLabel("Chọn collection và nhấn 'Tải dữ liệu'")
        self._status_lbl.setObjectName("bodyMuted")
        main.addWidget(self._status_lbl)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            f"QTableWidget {{ alternate-background-color: {C['surface_container_low']}; }}"
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setMinimumHeight(400)
        main.addWidget(self._table)

        main.addStretch()
        scroll.setWidget(content)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

        self._all_rows: list[dict] = []

    def _fetch_data(self) -> None:
        collection = self._collection_combo.currentText()
        self._status_lbl.setText(f"Đang tải {collection}…")
        self._table.clearContents()
        self._table.setRowCount(0)

        worker = _FetchWorker(collection)
        worker.signals.done.connect(self._on_data)
        self._pool.start(worker)

    @Slot(list, str)
    def _on_data(self, rows: list, error: str) -> None:
        if error:
            self._status_lbl.setText(f"Lỗi: {error}")
            return
        self._all_rows = rows
        self._status_lbl.setText(f"Đã tải {len(rows)} bản ghi.")
        self._populate_table(rows)

    def _populate_table(self, rows: list[dict]) -> None:
        if not rows:
            self._table.clearContents()
            self._table.setRowCount(0)
            return
        # Build columns from all keys
        cols: list[str] = ["id"]
        seen: set[str] = {"id"}
        for row in rows:
            for k in row:
                if k not in seen:
                    cols.append(k)
                    seen.add(k)

        self._table.setColumnCount(len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.setRowCount(len(rows))

        for r_idx, row in enumerate(rows):
            for c_idx, col in enumerate(cols):
                val = str(row.get(col, ""))
                item = QTableWidgetItem(val[:200])
                item.setToolTip(val)
                self._table.setItem(r_idx, c_idx, item)

    def _filter_table(self, query: str) -> None:
        q = query.lower()
        if not q:
            self._populate_table(self._all_rows)
            return
        filtered = [
            r for r in self._all_rows
            if any(q in str(v).lower() for v in r.values())
        ]
        self._populate_table(filtered)

    @Slot(str)
    def log_line(self, _msg: str) -> None:
        pass
