"""
Unit and integration tests for IoT QR scanning system.
Tests cover QR decryption, validation, and appointment workflow.
"""

import unittest
import base64
import json
import time
from unittest.mock import Mock, patch, MagicMock
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from qr_scan import (
    decrypt_patient_id,
    _is_likely_qr_payload,
    _decode_qr,
    _extract_patient_name,
    _normalize_appointment_date,
    _format_hhmm,
    _process_payload_and_update,
    _is_arrived_checkin_message,
    _extract_checkin_info,
    _wrap_result_text_lines,
)


class TestQRDecryption(unittest.TestCase):
    """Test AES-GCM decryption of QR payloads."""

    def setUp(self):
        """Set up test encryption keys and sample data."""
        # Generate test key (32 bytes for AES-256)
        self.test_key = b'\x00' * 32
        self.keys = [self.test_key]
        
    def _encrypt_test_payload(self, patient_id: str, key: bytes = None) -> str:
        """Helper to encrypt patient ID for testing."""
        if key is None:
            key = self.test_key
        
        nonce = b'\x00' * 12
        aesgcm = AESGCM(key)
        plaintext = patient_id.encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        payload = nonce + ciphertext
        return base64.b64encode(payload).decode("utf-8")

    def test_decrypt_valid_payload(self):
        """Test successful decryption of valid AES-GCM payload."""
        patient_id = "P123456"
        encrypted = self._encrypt_test_payload(patient_id)
        
        result = decrypt_patient_id(encrypted, self.keys)
        self.assertEqual(result, patient_id)

    def test_decrypt_payload_with_v1_prefix(self):
        """Test decryption of v1: prefixed payload."""
        patient_id = "P789012"
        encrypted = self._encrypt_test_payload(patient_id)
        prefixed = f"v1:{encrypted}"
        
        result = decrypt_patient_id(prefixed, self.keys)
        self.assertEqual(result, patient_id)

    def test_decrypt_invalid_key(self):
        """Test decryption fails with wrong key."""
        patient_id = "P999999"
        encrypted = self._encrypt_test_payload(patient_id, self.test_key)
        
        wrong_key = b'\xFF' * 32
        with self.assertRaises(ValueError) as ctx:
            decrypt_patient_id(encrypted, [wrong_key])
        
        self.assertIn("Không giải mã được", str(ctx.exception))

    def test_decrypt_short_payload(self):
        """Test decryption rejects payload shorter than 12 bytes."""
        short_payload = base64.b64encode(b"short").decode("utf-8")
        
        with self.assertRaises(ValueError):
            decrypt_patient_id(short_payload, self.keys)

    def test_decrypt_invalid_base64(self):
        """Test decryption rejects invalid base64."""
        invalid_b64 = "!!!invalid_base64!!!"
        
        with self.assertRaises(ValueError):
            decrypt_patient_id(invalid_b64, self.keys)

    def test_decrypt_multi_key_fallback(self):
        """Test decryption tries multiple keys until success."""
        patient_id = "P111222"
        
        # Encrypt with second key
        key2 = b'\xAA' * 32
        encrypted = self._encrypt_test_payload(patient_id, key2)
        
        # Try with wrong key first, then correct key
        keys = [self.test_key, key2]
        result = decrypt_patient_id(encrypted, keys)
        self.assertEqual(result, patient_id)


class TestQRValidation(unittest.TestCase):
    """Test QR payload format validation."""

    def test_valid_base64_payload(self):
        """Test recognition of valid base64 QR payload."""
        valid_payload = base64.b64encode(b"test_data" * 4).decode("utf-8")
        self.assertTrue(_is_likely_qr_payload(valid_payload))

    def test_valid_v1_prefixed_payload(self):
        """Test recognition of v1: prefixed payload."""
        payload = base64.b64encode(b"test_data" * 4).decode("utf-8")
        prefixed = f"v1:{payload}"
        self.assertTrue(_is_likely_qr_payload(prefixed))

    def test_invalid_too_short(self):
        """Test rejection of payload too short."""
        short = base64.b64encode(b"short").decode("utf-8")
        self.assertFalse(_is_likely_qr_payload(short))

    def test_invalid_non_base64_chars(self):
        """Test rejection of payload with invalid base64 characters."""
        invalid = "ABCD****EFGH"  # * is not valid base64
        self.assertFalse(_is_likely_qr_payload(invalid))

    def test_invalid_not_aligned_4(self):
        """Test rejection of payload not aligned to 4-byte boundary."""
        # Valid base64 but not multiple of 4
        invalid = "AB=="  # 4 bytes, but content too short
        self.assertFalse(_is_likely_qr_payload(invalid))

    def test_invalid_none_input(self):
        """Test rejection of None input."""
        self.assertFalse(_is_likely_qr_payload(None))

    def test_invalid_empty_string(self):
        """Test rejection of empty string."""
        self.assertFalse(_is_likely_qr_payload(""))


class TestQRDecode(unittest.TestCase):
    """Test QR code image decoding."""

    @patch('qr_scan.pyzbar.decode')
    def test_decode_qr_success(self, mock_decode):
        """Test successful QR code decoding from image."""
        import numpy as np
        
        # Mock pyzbar to return QR code
        mock_code = Mock()
        mock_code.data = b"decoded_qr_data"
        mock_decode.return_value = [mock_code]
        
        images = [np.zeros((100, 100, 3), dtype=np.uint8)]
        result = _decode_qr(images)
        
        self.assertEqual(result, "decoded_qr_data")
        mock_decode.assert_called_once()

    @patch('qr_scan.pyzbar.decode')
    def test_decode_qr_first_image_success(self, mock_decode):
        """Test decode stops at first successful image."""
        import numpy as np
        
        mock_code = Mock()
        mock_code.data = b"qr_payload"
        
        # Only second image has QR code
        mock_decode.side_effect = [[], [mock_code]]
        
        images = [
            np.zeros((100, 100, 3), dtype=np.uint8),
            np.zeros((100, 100, 3), dtype=np.uint8),
        ]
        result = _decode_qr(images)
        
        self.assertEqual(result, "qr_payload")
        self.assertEqual(mock_decode.call_count, 2)

    @patch('qr_scan.pyzbar.decode')
    def test_decode_qr_no_match(self, mock_decode):
        """Test decode returns None when no QR found."""
        import numpy as np
        
        mock_decode.return_value = []
        
        images = [np.zeros((100, 100, 3), dtype=np.uint8)]
        result = _decode_qr(images)
        
        self.assertIsNone(result)


class TestPatientNameExtraction(unittest.TestCase):
    """Test extraction of patient name from various data formats."""

    def test_extract_name_standard_fields(self):
        """Test extraction of name from standard field names."""
        data = {"name": "Nguyễn Văn A"}
        self.assertEqual(_extract_patient_name(data), "Nguyễn Văn A")

    def test_extract_name_full_name(self):
        """Test extraction from fullName field."""
        data = {"fullName": "Trần Thị B"}
        self.assertEqual(_extract_patient_name(data), "Trần Thị B")

    def test_extract_name_patient_name(self):
        """Test extraction from patient_name field."""
        data = {"patient_name": "Phạm Minh C"}
        self.assertEqual(_extract_patient_name(data), "Phạm Minh C")

    def test_extract_name_vietnamese_variants(self):
        """Test extraction from Vietnamese field names."""
        data = {"ho_ten": "Lê Quang D"}
        self.assertEqual(_extract_patient_name(data), "Lê Quang D")
        
        data2 = {"hoTen": "Vũ Thanh E"}
        self.assertEqual(_extract_patient_name(data2), "Vũ Thanh E")

    def test_extract_name_priority_order(self):
        """Test field priority when multiple names present."""
        data = {
            "name": "Name A",
            "full_name": "Name B",
            "patient_name": "Name C",
        }
        # Should return first match in priority order
        result = _extract_patient_name(data)
        self.assertEqual(result, "Name A")

    def test_extract_name_empty_string(self):
        """Test extraction skips empty string values."""
        data = {"name": "", "patient_name": "Valid Name"}
        self.assertEqual(_extract_patient_name(data), "Valid Name")

    def test_extract_name_not_dict(self):
        """Test extraction returns empty for non-dict input."""
        self.assertEqual(_extract_patient_name(None), "")
        self.assertEqual(_extract_patient_name([]), "")
        self.assertEqual(_extract_patient_name("string"), "")


class TestDateNormalization(unittest.TestCase):
    """Test appointment date normalization."""

    def test_normalize_iso_format(self):
        """Test normalization of ISO format date."""
        result = _normalize_appointment_date("2026-06-19")
        self.assertEqual(result, "2026-06-19")

    def test_normalize_dmy_slash_format(self):
        """Test normalization of DD/MM/YYYY format."""
        result = _normalize_appointment_date("19/06/2026")
        self.assertEqual(result, "2026-06-19")

    def test_normalize_dmy_dash_format(self):
        """Test normalization of DD-MM-YYYY format."""
        result = _normalize_appointment_date("19-06-2026")
        self.assertEqual(result, "2026-06-19")

    def test_normalize_ymd_slash_format(self):
        """Test normalization of YYYY/MM/DD format."""
        result = _normalize_appointment_date("2026/06/19")
        self.assertEqual(result, "2026-06-19")

    def test_normalize_iso_datetime(self):
        """Test normalization strips time from ISO datetime."""
        result = _normalize_appointment_date("2026-06-19T10:30:00")
        self.assertEqual(result, "2026-06-19")

    def test_normalize_empty_string(self):
        """Test normalization of empty string."""
        result = _normalize_appointment_date("")
        self.assertEqual(result, "")

    def test_normalize_invalid_date(self):
        """Test normalization of invalid date."""
        result = _normalize_appointment_date("invalid-date")
        self.assertEqual(result, "")


class TestTimestampFormatting(unittest.TestCase):
    """Test formatting of timestamp to HH:MM."""

    def test_format_unix_timestamp(self):
        """Test formatting of Unix timestamp."""
        # Use a known timestamp
        ts = 1719878400  # 2026-06-19 12:00:00 UTC
        result = _format_hhmm(ts)
        self.assertRegex(result, r'\d{2}:\d{2}')

    def test_format_string_timestamp(self):
        """Test formatting of string timestamp."""
        result = _format_hhmm("1719878400")
        self.assertRegex(result, r'\d{2}:\d{2}')

    def test_format_float_timestamp(self):
        """Test formatting of float timestamp."""
        result = _format_hhmm(1719878400.5)
        self.assertRegex(result, r'\d{2}:\d{2}')

    def test_format_invalid_input(self):
        """Test formatting returns default for invalid input."""
        result = _format_hhmm("invalid")
        self.assertEqual(result, "--:--")


class TestCheckinMessageDetection(unittest.TestCase):
    """Test detection of check-in confirmation messages."""

    def test_detect_checkin_vietnamese(self):
        """Test detection of Vietnamese check-in message."""
        msg = "Bạn đã check in vào lúc 10:30"
        self.assertTrue(_is_arrived_checkin_message(msg))

    def test_detect_checkin_variant_1(self):
        """Test detection of check-in variant with dash."""
        msg = "Bạn đã check-in lúc 10:30"
        self.assertTrue(_is_arrived_checkin_message(msg))

    def test_detect_checkin_normalized(self):
        """Test detection of normalized check-in message."""
        msg = "Ban da check in vao luc 10:30"
        self.assertTrue(_is_arrived_checkin_message(msg))

    def test_detect_non_checkin_message(self):
        """Test rejection of non-check-in messages."""
        msgs = [
            "Lịch hẹn đã hủy",
            "Mã QR không hợp lệ",
            "Chương khám bệnh",
        ]
        for msg in msgs:
            self.assertFalse(_is_arrived_checkin_message(msg))

    def test_detect_empty_message(self):
        """Test handling of empty message."""
        self.assertFalse(_is_arrived_checkin_message(""))
        self.assertFalse(_is_arrived_checkin_message(None))


class TestCheckinInfoExtraction(unittest.TestCase):
    """Test extraction of check-in time and queue number from message."""

    def test_extract_time_and_queue(self):
        """Test extraction of both time and queue number."""
        msg = "Bạn đã check in vào lúc 10:30\nSố thứ tự: 5"
        time, queue = _extract_checkin_info(msg)
        self.assertEqual(time, "10:30")
        self.assertEqual(queue, "5")

    def test_extract_time_only(self):
        """Test extraction when queue number missing."""
        msg = "Bạn đã check in vào lúc 14:45"
        time, queue = _extract_checkin_info(msg)
        self.assertEqual(time, "14:45")
        self.assertEqual(queue, "---")

    def test_extract_vietnamese_variants(self):
        """Test extraction with Vietnamese field variants."""
        msg = "Bạn đã check in vào lúc 09:15\nSo thu tu: 12"
        time, queue = _extract_checkin_info(msg)
        self.assertEqual(time, "09:15")
        self.assertEqual(queue, "12")

    def test_extract_none_input(self):
        """Test extraction handles None input."""
        time, queue = _extract_checkin_info(None)
        self.assertEqual(time, "--:--")
        self.assertEqual(queue, "---")


class TestTextWrapping(unittest.TestCase):
    """Test text wrapping for display."""

    def test_wrap_short_text(self):
        """Test wrapping of text shorter than limit."""
        text = "Short text"
        result = _wrap_result_text_lines(text, width=40)
        self.assertEqual(result, text)

    def test_wrap_long_text(self):
        """Test wrapping of long text."""
        text = "A" * 80  # 80 characters, width 40
        result = _wrap_result_text_lines(text, width=40)
        lines = result.split("\n")
        self.assertGreaterEqual(len(lines), 2)
        for line in lines:
            self.assertLessEqual(len(line), 40)

    def test_wrap_multiline_text(self):
        """Test wrapping preserves line breaks."""
        text = "Line 1\nLine 2 with longer text"
        result = _wrap_result_text_lines(text, width=40)
        lines = result.split("\n")
        self.assertGreaterEqual(len(lines), 2)

    def test_wrap_empty_lines(self):
        """Test wrapping preserves empty lines."""
        text = "Text\n\nMore text"
        result = _wrap_result_text_lines(text, width=40)
        self.assertIn("\n\n", result)


class TestProcessPayloadIntegration(unittest.TestCase):
    """Integration tests for full payload processing workflow."""

    def setUp(self):
        """Set up for integration tests."""
        self.test_key = b'\x00' * 32
        self.keys = [self.test_key]

    def _encrypt_appointment_id(self, appt_id: str) -> str:
        """Helper to encrypt appointment ID."""
        nonce = b'\x00' * 12
        aesgcm = AESGCM(self.test_key)
        plaintext = appt_id.encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        payload = nonce + ciphertext
        return base64.b64encode(payload).decode("utf-8")

    @patch('qr_scan.get_db_ref')
    @patch('qr_scan._load_keys')
    @patch('qr_scan.get_appointment')
    @patch('qr_scan.get_patient')
    @patch('qr_scan.add_patient_to_queue')
    @patch('qr_scan.update_global_appointment_fields')
    def test_process_scheduled_appointment(self, mock_update, mock_queue, 
                                          mock_patient, mock_appt, mock_keys, mock_db_ref):
        """Test processing of scheduled appointment that hasn't been checked in."""
        mock_keys.return_value = self.keys
        
        appt_id = "APT001"
        payload = self._encrypt_appointment_id(appt_id)
        
        mock_appt.return_value = {
            "id": appt_id,
            "status": "scheduled",
            "patientID": "P001",
            "doctorID": "D001",
            "date": "2026-06-19",
        }
        
        mock_patient.return_value = {
            "id": "P001",
            "name": "Nguyễn Văn A",
        }
        
        mock_queue.return_value = 5
        mock_update.return_value = True
        # Mock direct write to fail so fallback is called
        mock_db_ref.side_effect = Exception("Direct write failed")
        
        message, patient_name = _process_payload_and_update(payload)
        
        self.assertEqual(patient_name, "Nguyễn Văn A")
        self.assertEqual(message, "")
        mock_update.assert_called_once()

    @patch('qr_scan._load_keys')
    @patch('qr_scan.get_appointment')
    def test_process_cancelled_appointment(self, mock_appt, mock_keys):
        """Test processing of cancelled appointment."""
        mock_keys.return_value = self.keys
        
        appt_id = "APT002"
        payload = self._encrypt_appointment_id(appt_id)
        
        mock_appt.return_value = {
            "id": appt_id,
            "status": "cancelled",
            "patientID": "P001",
        }
        
        message, patient_name = _process_payload_and_update(payload)
        
        self.assertIn("hủy", message.lower())
        self.assertEqual(patient_name, "")

    @patch('qr_scan._load_keys')
    @patch('qr_scan.get_appointment')
    def test_process_expired_appointment(self, mock_appt, mock_keys):
        """Test processing of expired (no-show) appointment."""
        mock_keys.return_value = self.keys
        
        appt_id = "APT003"
        payload = self._encrypt_appointment_id(appt_id)
        
        mock_appt.return_value = {
            "id": appt_id,
            "status": "no_show",
            "patientID": "P001",
        }
        
        message, patient_name = _process_payload_and_update(payload)
        
        self.assertIn("quá hẹn", message.lower())
        self.assertEqual(patient_name, "")

    @patch('qr_scan._load_keys')
    @patch('qr_scan.get_appointment')
    def test_process_completed_appointment(self, mock_appt, mock_keys):
        """Test processing of already completed appointment."""
        mock_keys.return_value = self.keys
        
        appt_id = "APT004"
        payload = self._encrypt_appointment_id(appt_id)
        
        mock_appt.return_value = {
            "id": appt_id,
            "status": "completed",
            "patientID": "P001",
        }
        
        message, patient_name = _process_payload_and_update(payload)
        
        self.assertIn("hoàn tất", message.lower())

    @patch('qr_scan._load_keys')
    @patch('qr_scan.get_appointment')
    def test_process_invalid_decryption(self, mock_appt, mock_keys):
        """Test processing with invalid encrypted payload."""
        mock_keys.return_value = []
        
        payload = "invalid_encrypted_data"
        
        message, patient_name = _process_payload_and_update(payload)
        
        self.assertIn("Lỗi", message)
        self.assertEqual(patient_name, "")

    @patch('qr_scan._load_keys')
    @patch('qr_scan.get_appointment')
    def test_process_appointment_not_found(self, mock_appt, mock_keys):
        """Test processing when appointment doesn't exist."""
        mock_keys.return_value = self.keys
        
        appt_id = "APT999"
        payload = self._encrypt_appointment_id(appt_id)
        
        mock_appt.return_value = None
        
        message, patient_name = _process_payload_and_update(payload)
        
        self.assertIn("Không tìm thấy", message)


class TestAppointmentDateValidation(unittest.TestCase):
    """Test date validation for check-in workflow."""

    @patch('qr_scan._load_keys')
    @patch('qr_scan.get_appointment')
    @patch('qr_scan.time')
    def test_checkin_future_appointment(self, mock_time, mock_appt, mock_keys):
        """Test rejection of check-in for future appointment."""
        mock_keys.return_value = [b'\x00' * 32]
        
        # Mock current date as 2026-06-18
        mock_time.strftime.return_value = "2026-06-18"
        mock_time.localtime.return_value = time.localtime()
        
        appt_id = "APT_FUTURE"
        nonce = b'\x00' * 12
        aesgcm = AESGCM(b'\x00' * 32)
        ciphertext = aesgcm.encrypt(nonce, appt_id.encode("utf-8"), None)
        payload = base64.b64encode(nonce + ciphertext).decode("utf-8")
        
        mock_appt.return_value = {
            "id": appt_id,
            "status": "scheduled",
            "date": "2026-06-19",  # Tomorrow
            "patientID": "P001",
        }
        
        message, _ = _process_payload_and_update(payload)
        
        self.assertIn("Chưa đến ngày", message)

    @patch('qr_scan._load_keys')
    @patch('qr_scan.get_appointment')
    @patch('qr_scan.time')
    def test_checkin_past_appointment(self, mock_time, mock_appt, mock_keys):
        """Test rejection of check-in for past appointment."""
        mock_keys.return_value = [b'\x00' * 32]
        
        # Mock current date as 2026-06-20
        mock_time.strftime.return_value = "2026-06-20"
        mock_time.localtime.return_value = time.localtime()
        
        appt_id = "APT_PAST"
        nonce = b'\x00' * 12
        aesgcm = AESGCM(b'\x00' * 32)
        ciphertext = aesgcm.encrypt(nonce, appt_id.encode("utf-8"), None)
        payload = base64.b64encode(nonce + ciphertext).decode("utf-8")
        
        mock_appt.return_value = {
            "id": appt_id,
            "status": "scheduled",
            "date": "2026-06-19",  # Yesterday
            "patientID": "P001",
        }
        
        message, _ = _process_payload_and_update(payload)
        
        # Past appointments are treated as expired/no-show
        self.assertIn("quá hạn", message.lower())


def suite():
    """Combine all test suites."""
    test_suite = unittest.TestSuite()
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestQRDecryption))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestQRValidation))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestQRDecode))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestPatientNameExtraction))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestDateNormalization))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestTimestampFormatting))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestCheckinMessageDetection))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestCheckinInfoExtraction))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestTextWrapping))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestProcessPayloadIntegration))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAppointmentDateValidation))
    return test_suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())
