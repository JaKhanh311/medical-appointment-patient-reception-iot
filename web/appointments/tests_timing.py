"""
Timing tests — đo thời gian từng bước quan trọng trong dashboard và navigation flow.
Chạy:  python manage.py test appointments.tests_timing -v 2
"""

import json
import time
import statistics
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse

# ---------- helpers ----------

FAKE_DOCTOR_ID = "doc_timing_test"
FAKE_PATIENT_ID = "patient_timing_1"
FAKE_APT_ID = "apt_timing_1"

FAKE_APPOINTMENTS_PAYLOAD = [
    {
        "id": f"apt_{i}",
        "appointmentID": f"apt_{i}",
        "patientID": f"patient_{i}",
        "session": "morning" if i % 2 == 0 else "afternoon",
        "time": f"0{(8 + i % 4)}:00",
        "status": "waiting" if i % 3 == 0 else "scheduled",
        "doctorID": FAKE_DOCTOR_ID,
        "date": "2026-05-10",
    }
    for i in range(10)
]

FAKE_PATIENTS_MAP = {
    f"patient_{i}": {
        "name": f"Bệnh nhân Số {i}",
        "phone": f"090000{i:04d}",
        "gender": "male",
        "birthdate": "1990-01-01",
    }
    for i in range(10)
}


def _avg_ms(timings):
    return round(statistics.mean(timings) * 1000, 2)


def _max_ms(timings):
    return round(max(timings) * 1000, 2)


def _print_result(label, timings, warn_ms=300):
    avg = _avg_ms(timings)
    mx = _max_ms(timings)
    flag = "  ⚠️  SLOW" if mx > warn_ms else ""
    print(f"  [{label}]  avg={avg}ms  max={mx}ms{flag}")


REPEATS = 5  # số lần lặp để lấy trung bình


class TimingDashboardView(TestCase):
    def setUp(self):
        self.client = Client()
        s = self.client.session
        s["doctor_id"] = FAKE_DOCTOR_ID
        s["doctor_name"] = "BS. Test"
        s.save()

    @patch("appointments.views._load_queue_lookup_for_date", return_value={})
    @patch("appointments.views.get_patients_by_ids", return_value=FAKE_PATIENTS_MAP)
    @patch(
        "appointments.views.get_appointments_by_date_for_doctor",
        return_value=FAKE_APPOINTMENTS_PAYLOAD,
    )
    def test_01_dashboard_page_load(self, *mocks):
        """Tải trang dashboard chính (GET /dashboard/)."""
        url = reverse("dashboard")
        timings = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            resp = self.client.get(url)
            timings.append(time.perf_counter() - t0)
        self.assertEqual(resp.status_code, 200)
        print("\n--- Dashboard page load ---")
        _print_result("GET /dashboard/", timings)

    @patch("appointments.views._load_queue_lookup_for_date", return_value={})
    @patch("appointments.views.get_patients_by_ids", return_value=FAKE_PATIENTS_MAP)
    @patch(
        "appointments.views.get_appointments_by_date_for_doctor",
        return_value=FAKE_APPOINTMENTS_PAYLOAD,
    )
    def test_02_dashboard_poll_cold(self, *mocks):
        """Poll endpoint lần đầu (không có snapshot_key)."""
        url = reverse("dashboard_poll")
        timings = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            resp = self.client.get(url + "?date=2026-05-10")
            timings.append(time.perf_counter() - t0)
        self.assertEqual(resp.status_code, 200)
        print("\n--- Dashboard poll (cold) ---")
        _print_result("GET /dashboard/poll/ no snapshot", timings)

    @patch("appointments.views._load_queue_lookup_for_date", return_value={})
    @patch("appointments.views.get_patients_by_ids", return_value=FAKE_PATIENTS_MAP)
    @patch(
        "appointments.views.get_appointments_by_date_for_doctor",
        return_value=FAKE_APPOINTMENTS_PAYLOAD,
    )
    def test_03_dashboard_poll_warm(self, *mocks):
        """Poll endpoint với snapshot_key khớp (không thay đổi — fast path)."""
        url = reverse("dashboard_poll")
        # warm call để lấy snapshot key
        resp0 = self.client.get(url + "?date=2026-05-10")
        snap = resp0.json().get("snapshot_key", "")

        timings = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            resp = self.client.get(url + f"?date=2026-05-10&snapshot_key={snap}")
            timings.append(time.perf_counter() - t0)
        self.assertEqual(resp.status_code, 200)
        print("\n--- Dashboard poll (warm / no-change) ---")
        _print_result("GET /dashboard/poll/ same snapshot", timings, warn_ms=80)

    @patch("appointments.views._load_queue_lookup_for_date", return_value={})
    @patch("appointments.views.get_patients_by_ids", return_value=FAKE_PATIENTS_MAP)
    @patch(
        "appointments.views.get_appointments_by_date_for_doctor",
        return_value=FAKE_APPOINTMENTS_PAYLOAD,
    )
    def test_04_build_dashboard_context_direct(self, mock_apts, mock_patients, mock_queue):
        """Gọi _build_dashboard_context trực tiếp — đo chi phí thuần xử lý data."""
        from appointments.views import _build_dashboard_context

        request = MagicMock()
        request.session = {"doctor_id": FAKE_DOCTOR_ID, "doctor_name": "BS. Test"}

        from datetime import date
        today = date(2026, 5, 10)

        timings = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            ctx = _build_dashboard_context(request, today, "")
            timings.append(time.perf_counter() - t0)

        self.assertIn("all_today_appointments", ctx)
        print("\n--- _build_dashboard_context direct ---")
        _print_result("_build_dashboard_context()", timings, warn_ms=100)
        # breakdowns
        apts = ctx["all_today_appointments"]
        print(f"    appointments processed: {len(apts)}")

    @patch("appointments.views._load_queue_lookup_for_date", return_value={})
    @patch("appointments.views.get_patients_by_ids", return_value=FAKE_PATIENTS_MAP)
    @patch(
        "appointments.views.get_appointments_by_date_for_doctor",
        return_value=FAKE_APPOINTMENTS_PAYLOAD,
    )
    def test_05_examine_view_get(self, *mocks):
        """Tải trang khám bệnh (GET /appointments/examine/<id>/)."""
        from unittest.mock import patch as _patch

        fake_apt = {
            "id": FAKE_APT_ID,
            "doctorID": FAKE_DOCTOR_ID,
            "patientID": FAKE_PATIENT_ID,
            "date": "2026-05-10",
            "time": "08:00",
            "status": "waiting",
            "patient_info": {
                "id": FAKE_PATIENT_ID,
                "name": "Bệnh Nhân Test",
                "gender": "male",
                "birthdate": "1990-01-01",
                "phone": "0900000000",
            },
        }

        with _patch(
            "services.RTDB_utils.get_appointment_with_patient_info",
            return_value=fake_apt,
        ), _patch(
            "services.RTDB_utils.get_patient_medical_records_for_doctor",
            return_value=[],
        ):
            url = reverse("examine", args=[FAKE_APT_ID])
            timings = []
            for _ in range(REPEATS):
                t0 = time.perf_counter()
                resp = self.client.get(url)
                timings.append(time.perf_counter() - t0)

        self.assertEqual(resp.status_code, 200)
        # Medical records are now loaded via AJAX — verify the AJAX URL is in the page
        self.assertIn(b"medical-records-section", resp.content,
                      "examine page should contain AJAX medical records container")
        print("\n--- Examine view ---")
        _print_result("GET /appointments/examine/<id>/", timings)
        print("  Medical records: AJAX (non-blocking) ✓")

    @patch("appointments.views._load_queue_lookup_for_date", return_value={})
    @patch("appointments.views.get_patients_by_ids", return_value=FAKE_PATIENTS_MAP)
    @patch(
        "appointments.views.get_appointments_by_date_for_doctor",
        return_value=FAKE_APPOINTMENTS_PAYLOAD,
    )
    def test_06_patient_display_poll(self, *mocks):
        """Poll phòng chờ bệnh nhân (GET /dashboard/patient-display/poll/)."""
        url = reverse("patient_display_poll")
        timings = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            resp = self.client.get(url + "?date=2026-05-10")
            timings.append(time.perf_counter() - t0)
        self.assertEqual(resp.status_code, 200)
        print("\n--- Patient display poll ---")
        _print_result("GET /dashboard/patient-display/poll/", timings)

    @patch("appointments.views._load_queue_lookup_for_date", return_value={})
    @patch("appointments.views.get_patients_by_ids", return_value=FAKE_PATIENTS_MAP)
    @patch(
        "appointments.views.get_appointments_by_date_for_doctor",
        return_value=FAKE_APPOINTMENTS_PAYLOAD,
    )
    def test_07_patient_display_view(self, *mocks):
        """Tải trang phòng chờ bệnh nhân (GET /appointments/patient-display/)."""
        url = reverse("patient_display")
        timings = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            resp = self.client.get(url + "?date=2026-05-10")
            timings.append(time.perf_counter() - t0)
        self.assertEqual(resp.status_code, 200)
        print("\n--- Patient display view ---")
        _print_result("GET /appointments/patient-display/", timings)

    @patch("appointments.views._load_queue_lookup_for_date", return_value={})
    @patch("appointments.views.get_patients_by_ids", return_value=FAKE_PATIENTS_MAP)
    @patch(
        "appointments.views.get_appointments_by_date_for_doctor",
        return_value=FAKE_APPOINTMENTS_PAYLOAD,
    )
    def test_08_appointment_detail_api(self, *mocks):
        """API chi tiết lịch hẹn (GET /appointments/api/detail/<id>/)."""
        # warm cache
        self.client.get(reverse("dashboard_poll") + "?date=2026-05-10")

        url = reverse("appointment_detail_api", args=["apt_0"])
        timings = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            resp = self.client.get(url + "?date=2026-05-10")
            timings.append(time.perf_counter() - t0)
        self.assertIn(resp.status_code, (200, 404))
        print("\n--- Appointment detail API ---")
        _print_result("GET /appointments/api/detail/<id>/", timings, warn_ms=100)

    @patch("appointments.views._ensure_tts_files_for_appointment")
    def test_09_tts_prefetch_view(self, mock_tts):
        """TTS prefetch endpoint — đo chi phí ngoài phần sinh file audio."""
        mock_tts.return_value = {
            "call_url": "/static/generated_tts/test_call.mp3",
            "remind_url": "/static/generated_tts/test_remind.mp3",
            "call_text": "Mời bệnh nhân Test vào phòng khám",
            "remind_text": "Xin nhắc lại mời bệnh nhân TEST vào phòng khám",
        }
        url = reverse("dashboard_tts_prefetch")
        payload = json.dumps({"appointment_id": "apt_0", "name": "Test"})

        from django.test import RequestFactory
        timings = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            resp = self.client.post(
                url,
                data=payload,
                content_type="application/json",
            )
            timings.append(time.perf_counter() - t0)

        self.assertEqual(resp.status_code, 200)
        print("\n--- TTS prefetch (audio generation mocked) ---")
        _print_result("POST /dashboard/tts-prefetch/", timings, warn_ms=100)

    def test_99_summary(self):
        """Phần tóm tắt — in tổng quan gợi ý tối ưu."""
        print(
            "\n"
            "====================================================\n"
            "  SUMMARY — gợi ý điểm cần tối ưu:\n"
            "  • _build_dashboard_context   → Firebase I/O chính\n"
            "  • GET /dashboard/            → render + context build\n"
            "  • GET /dashboard/poll/ cold  → giống dashboard nhưng JSON\n"
            "  • GET /dashboard/poll/ warm  → nên < 30ms (cache hit)\n"
            "  • TTS prefetch               → nên < 50ms (đã mock audio)\n"
            "  Nếu bước nào > 300ms → xem ⚠️  ở trên.\n"
            "===================================================="
        )
        self.assertTrue(True)
