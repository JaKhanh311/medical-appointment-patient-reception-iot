import json

from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch


class ScanViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        # simulate logged-in doctor by session
        session = self.client.session
        session['doctor_id'] = 'dummy'
        session.save()

    def test_get_scan_page_requires_login(self):
        # user not logged in should be redirected by middleware
        self.client.session.flush()
        resp = self.client.get(reverse('scan'))
        self.assertEqual(resp.status_code, 302)
        # after restoring login, page loads
        session = self.client.session
        session['doctor_id'] = 'dummy'; session.save()
        resp = self.client.get(reverse('scan'))
        self.assertEqual(resp.status_code, 200)

    @patch('appointments.views.mark_appointment_arrived')
    def test_post_scan_success(self, mock_mark):
        mock_mark.return_value = {'id': 'apt1', 'status': 'Đã đến'}
        resp = self.client.post(
            reverse('scan'),
            data='{"appointment_id":"apt1"}',
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('success'))
        mock_mark.assert_called_with('apt1')

    def test_post_scan_missing_id(self):
        resp = self.client.post(
            reverse('scan'),
            data='{}',
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get('success'))


class DashboardPriorityScopeTests(TestCase):
    def setUp(self):
        self.client = Client()
        session = self.client.session
        session['doctor_id'] = 'dummy'
        session.save()

    @patch('appointments.views.get_patients_by_ids')
    @patch('appointments.views.get_appointments_by_date_for_doctor')
    def test_priority_applies_only_to_selected_appointment_session(self, mock_get_appointments, mock_get_patients):
        mock_get_appointments.return_value = [
            {
                'id': 'apt-morning',
                'appointmentID': 'apt-morning',
                'patientID': 'patient-1',
                'session': 'morning',
                'time': '08:00',
                'status': 'scheduled',
            },
            {
                'id': 'apt-afternoon',
                'appointmentID': 'apt-afternoon',
                'patientID': 'patient-1',
                'session': 'afternoon',
                'time': '13:30',
                'status': 'scheduled',
            },
        ]
        mock_get_patients.return_value = {
            'patient-1': {
                'name': 'Nguyen Van A',
                'phone': '0900000000',
                'gender': 'male',
                'birthdate': '2000-01-01',
            }
        }

        post_response = self.client.post(
            reverse('update_priority'),
            data=json.dumps({
                'appointment_id': 'apt-afternoon',
                'patient_id': 'patient-1',
                'session_key': 'afternoon',
                'is_priority': True,
                'priority_reason': 'Người cao tuổi',
            }),
            content_type='application/json',
        )

        self.assertEqual(post_response.status_code, 200)
        self.assertTrue(post_response.json().get('success'))

        dashboard_response = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard_response.status_code, 200)

        appointments = {
            item['appointment_id']: item
            for item in dashboard_response.context['all_today_appointments']
        }

        self.assertFalse(appointments['apt-morning']['isPriority'])
        self.assertTrue(appointments['apt-afternoon']['isPriority'])
        self.assertEqual(appointments['apt-afternoon']['priorityReason'], 'Người cao tuổi')

    @patch('appointments.views.get_patients_by_ids')
    @patch('appointments.views.get_appointments_by_date_for_doctor')
    def test_dashboard_deduplicates_duplicate_appointments(self, mock_get_appointments, mock_get_patients):
        mock_get_appointments.return_value = [
            {
                'id': 'apt-duplicate',
                'appointmentID': 'apt-duplicate',
                'patientID': 'patient-1',
                'session': 'morning',
                'time': '08:00',
                'status': 'waiting',
            },
            {
                'id': 'apt-duplicate',
                'appointmentID': 'apt-duplicate',
                'patientID': 'patient-1',
                'session': 'morning',
                'time': '08:00',
                'status': 'waiting',
            },
        ]
        mock_get_patients.return_value = {
            'patient-1': {
                'name': 'Nguyen Van A',
                'phone': '0900000000',
                'gender': 'male',
                'birthdate': '2000-01-01',
            }
        }

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['all_today_appointments']), 1)
        self.assertEqual(response.context['dashboard_stats']['total'], 1)


class PatientDisplayFilteringTests(TestCase):
    def setUp(self):
        self.client = Client()
        session = self.client.session
        session['doctor_id'] = 'dummy'
        session.save()

    @patch('appointments.views._build_dashboard_context')
    def test_patient_display_shows_only_arrived_patients(self, mock_build_context):
        mock_build_context.return_value = {
            'all_today_appointments': [
                {'appointment_id': 'apt-arrived', 'status_key': 'waiting', 'status': 'Đã đến'},
                {'appointment_id': 'apt-scheduled', 'status_key': 'scheduled', 'status': 'Chưa đến'},
                {'appointment_id': 'apt-cancelled', 'status_key': 'cancelled', 'status': 'Đã hủy'},
                {'appointment_id': 'apt-no-show', 'status_key': 'no_show', 'status': 'Quá hẹn'},
            ],
        }

        response = self.client.get(reverse('patient_display'))

        self.assertEqual(response.status_code, 200)
        visible_ids = [
            item['appointment_id']
            for item in response.context['all_today_appointments']
        ]
        self.assertEqual(visible_ids, ['apt-arrived'])
        self.assertEqual(response.context['serving_appointment']['appointment_id'], 'apt-arrived')
        self.assertEqual(response.context['next_up_appointments'], [])


class NormalizeStatusTests(TestCase):
    def test_normalize_status_maps_no_show(self):
        from appointments.views import normalize_status

        status_key, status_label = normalize_status('no_show')

        self.assertEqual(status_key, 'no_show')
        self.assertEqual(status_label, 'Quá hẹn')


class SaveExaminationTests(TestCase):
    @patch('services.RTDB_utils.add_medical_record')
    @patch('services.RTDB_utils.update_appointment')
    @patch('services.RTDB_utils.get_appointment_by_id')
    def test_save_examination_adds_patient_and_appointment_ids_to_medical_record(
        self,
        mock_get_appointment,
        mock_update_appointment,
        mock_add_medical_record,
    ):
        from services.RTDB_utils import save_examination

        mock_get_appointment.side_effect = [
            {
                'id': 'apt-1',
                'patientID': 'patient-1',
                'doctorID': 'doctor-1',
                'specialtyID': 'spec-1',
                'date': '2026-04-24',
                'time': '08:00',
            },
            {
                'id': 'apt-1',
                'patientID': 'patient-1',
                'status': 'Đã khám',
            },
        ]

        save_examination(
            'apt-1',
            symptoms='Ho, sot',
            diagnosis='Cam cum',
            advice='Nghi ngoi',
            vital_signs={'pulse': '80'},
            prescription=[],
        )

        mock_add_medical_record.assert_called_once()
        call_args = mock_add_medical_record.call_args.args
        # New signature: add_medical_record(doctor_id, patient_id, record)
        doctor_id_arg, patient_id_arg, record_arg = call_args

        self.assertEqual(doctor_id_arg, 'doctor-1')
        self.assertEqual(patient_id_arg, 'patient-1')
        self.assertEqual(record_arg['patientID'], 'patient-1')
        self.assertEqual(record_arg['appointmentID'], 'apt-1')


class ExamineViewAuthorizationTests(TestCase):
    def setUp(self):
        self.client = Client()
        session = self.client.session
        session['doctor_id'] = 'doc-1'
        session.save()

    @patch('services.RTDB_utils.get_patient_medical_records_for_doctor')
    @patch('services.RTDB_utils.get_appointment_with_patient_info')
    def test_examine_blocks_unrelated_doctor(self, mock_get_appointment, mock_get_records):
        mock_get_appointment.return_value = {
            'id': 'apt-1',
            'doctorID': 'doc-2',
            'patientID': 'patient-1',
            'patient_info': {
                'id': 'patient-1',
                'name': 'Patient One',
            },
        }

        response = self.client.get(reverse('examine', args=['apt-1']))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))
        mock_get_records.assert_not_called()

    @patch('services.RTDB_utils.update_appointment')
    @patch('services.RTDB_utils.get_patient_medical_records_for_doctor')
    @patch('services.RTDB_utils.get_appointment_with_patient_info')
    def test_examine_shows_records_for_related_doctor(
        self,
        mock_get_appointment,
        mock_get_records,
        mock_update_appointment,
    ):
        mock_get_appointment.return_value = {
            'id': 'apt-1',
            'doctorID': 'doc-1',
            'patientID': 'patient-1',
            'patient_info': {
                'id': 'patient-1',
                'name': 'Patient One',
                'gender': 'male',
                'birthdate': '1995-01-01',
            },
            'date': '2026-04-26',
            'time': '08:00',
        }
        mock_get_records.return_value = [
            {
                'recordID': 'entry_001',
                'examDate': '2026-04-20',
                'examTime': '09:00',
                'diagnosis': 'Cam cum',
                'symptoms': 'Ho',
                'advice': 'Nghi ngo i',
            }
        ]

        response = self.client.get(reverse('examine', args=['apt-1']))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['medical_records']), 1)
        mock_update_appointment.assert_not_called()
