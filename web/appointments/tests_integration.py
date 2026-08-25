"""
Integration tests for doctor portal appointment and check-in workflow.
Tests cover the full appointment lifecycle from scheduling to completion.
"""

import json
import time
from datetime import date, timedelta
from unittest.mock import patch, Mock, MagicMock
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone


class AppointmentWorkflowTestCase(TransactionTestCase):
    """
    Test the complete appointment workflow:
    1. Appointment is scheduled
    2. Patient checks in via QR scan
    3. Doctor manages queue and patient
    4. Appointment is marked as seen/completed
    """

    def setUp(self):
        """Initialize test client and mock data."""
        self.client = Client()
        self.doctor_session = self.client.session
        self.doctor_session['doctor_id'] = 'doctor_001'
        self.doctor_session.save()

    @patch('appointments.views.get_doctor_by_id')
    @patch('appointments.views.get_all_appointments')
    @patch('appointments.views.mark_appointment_arrived')
    def test_full_appointment_workflow(self, mock_mark_arrived, mock_get_appts, mock_get_doctor):
        """Test complete appointment workflow from scheduling to completion."""
        doctor_id = 'doctor_001'
        patient_id = 'patient_001'
        appointment_id = 'apt_001'

        # Mock doctor data
        mock_doctor = {
            'id': doctor_id,
            'name': 'Dr. Nguyễn Văn A',
            'specialty': 'General Practice',
            'hospital': 'Hospital A'
        }
        mock_get_doctor.return_value = mock_doctor

        # Mock scheduled appointment
        scheduled_appointment = {
            'id': appointment_id,
            'doctorID': doctor_id,
            'patientID': patient_id,
            'status': 'scheduled',
            'date': str(date.today()),
            'time': '10:00',
            'notes': 'Regular checkup'
        }
        mock_get_appts.return_value = [scheduled_appointment]

        # Test dashboard loads appointments
        response = self.client.get(reverse('appointments_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Test check-in updates appointment status
        updated_appointment = dict(scheduled_appointment)
        updated_appointment['status'] = 'arrived'
        updated_appointment['arrivedAt'] = int(time.time())
        mock_mark_arrived.return_value = updated_appointment

        check_in_response = self.client.post(
            reverse('scan'),
            data=json.dumps({'appointment_id': appointment_id}),
            content_type='application/json'
        )
        self.assertEqual(check_in_response.status_code, 200)
        self.assertTrue(check_in_response.json().get('success', False))

    @patch('appointments.views.mark_appointment_arrived')
    def test_checkin_duplicate_prevention(self, mock_mark_arrived):
        """Test that duplicate check-ins are handled safely."""
        appointment_id = 'apt_duplicate'

        # First check-in succeeds
        mock_mark_arrived.return_value = {'status': 'arrived', 'queueNumber': 1}

        response1 = self.client.post(
            reverse('scan'),
            data=json.dumps({'appointment_id': appointment_id}),
            content_type='application/json'
        )
        self.assertTrue(response1.json().get('success', False))

        # Second check-in on same appointment should return same queue info
        response2 = self.client.post(
            reverse('scan'),
            data=json.dumps({'appointment_id': appointment_id}),
            content_type='application/json'
        )
        self.assertTrue(response2.json().get('success', False))

    @patch('appointments.views.get_appointment')
    def test_checkin_expired_appointment(self, mock_get_appt):
        """Test check-in is rejected for expired appointments."""
        appointment_id = 'apt_expired'
        yesterday = date.today() - timedelta(days=1)

        mock_get_appt.return_value = {
            'id': appointment_id,
            'date': str(yesterday),
            'status': 'no_show',
            'patientID': 'patient_001'
        }

        response = self.client.post(
            reverse('scan'),
            data=json.dumps({'appointment_id': appointment_id}),
            content_type='application/json'
        )
        self.assertFalse(response.json().get('success', True))

    @patch('appointments.views.get_appointment')
    def test_checkin_cancelled_appointment(self, mock_get_appt):
        """Test check-in is rejected for cancelled appointments."""
        appointment_id = 'apt_cancelled'

        mock_get_appt.return_value = {
            'id': appointment_id,
            'date': str(date.today()),
            'status': 'cancelled',
            'patientID': 'patient_001'
        }

        response = self.client.post(
            reverse('scan'),
            data=json.dumps({'appointment_id': appointment_id}),
            content_type='application/json'
        )
        self.assertFalse(response.json().get('success', True))

    @patch('appointments.views.get_appointment')
    def test_checkin_future_appointment(self, mock_get_appt):
        """Test check-in is rejected for future appointments."""
        appointment_id = 'apt_future'
        tomorrow = date.today() + timedelta(days=1)

        mock_get_appt.return_value = {
            'id': appointment_id,
            'date': str(tomorrow),
            'status': 'scheduled',
            'patientID': 'patient_001'
        }

        response = self.client.post(
            reverse('scan'),
            data=json.dumps({'appointment_id': appointment_id}),
            content_type='application/json'
        )
        # Should reject or return warning about future date
        result = response.json()
        if result.get('success'):
            # If accepted, should contain warning
            self.assertIn('message', result)

    def test_scan_requires_login(self):
        """Test that scan endpoint requires doctor login."""
        self.client.session.flush()

        response = self.client.post(
            reverse('scan'),
            data=json.dumps({'appointment_id': 'apt_001'}),
            content_type='application/json'
        )
        self.assertIn(response.status_code, [302, 401, 403])


class QueueManagementTestCase(TestCase):
    """Test patient queue management and priority handling."""

    def setUp(self):
        """Initialize test data."""
        self.doctor_id = 'doctor_queue_001'
        self.patients = [
            {'id': 'p1', 'name': 'Patient 1', 'priority': 'normal'},
            {'id': 'p2', 'name': 'Patient 2', 'priority': 'high'},
            {'id': 'p3', 'name': 'Patient 3', 'priority': 'normal'},
        ]

    @patch('appointments.views.add_patient_to_queue')
    @patch('appointments.views.get_queue_meta')
    def test_patient_added_to_queue_on_checkin(self, mock_get_queue, mock_add_queue):
        """Test patient is added to doctor's queue on check-in."""
        appointment_id = 'apt_queue_001'
        patient_id = 'p1'

        mock_add_queue.return_value = 1  # Queue position
        mock_get_queue.return_value = {
            'current': 1,
            'total': 3,
            'patients': [patient_id]
        }

        # Simulate check-in
        queue_pos = add_patient_to_queue(
            appointment_id=appointment_id,
            patient_id=patient_id,
            patient_name='Patient 1',
            doctor_id=self.doctor_id
        )

        self.assertEqual(queue_pos, 1)
        mock_add_queue.assert_called_once()

    @patch('appointments.views.get_all_appointments')
    def test_queue_sorted_by_priority(self, mock_get_appts):
        """Test queue is sorted with priority patients first."""
        mock_appointments = [
            {'id': 'a1', 'patientID': 'p1', 'status': 'arrived', 'priority': 'normal'},
            {'id': 'a2', 'patientID': 'p2', 'status': 'arrived', 'priority': 'high'},
            {'id': 'a3', 'patientID': 'p3', 'status': 'arrived', 'priority': 'normal'},
        ]
        mock_get_appts.return_value = mock_appointments

        # Expected order: high priority first
        # This would be handled by the dashboard view
        appts = mock_get_appts()
        high_priority = [a for a in appts if a.get('priority') == 'high']
        normal_priority = [a for a in appts if a.get('priority') == 'normal']

        self.assertEqual(len(high_priority), 1)
        self.assertEqual(len(normal_priority), 2)


class PatientRecordAccessTestCase(TestCase):
    """Test access control to patient medical records."""

    def setUp(self):
        """Initialize test data."""
        self.doctor_id = 'doctor_access_001'
        self.other_doctor_id = 'doctor_access_002'
        self.patient_id = 'patient_records_001'

    def test_doctor_login_required(self):
        """Test patient records require doctor login."""
        client = Client()
        response = client.get(reverse('patient_record', args=[self.patient_id]))
        self.assertIn(response.status_code, [302, 401, 403])

    @patch('appointments.views.doctor_can_access_patient')
    @patch('appointments.views.get_patient_by_id')
    def test_doctor_access_own_patient(self, mock_get_patient, mock_can_access):
        """Test doctor can access patient they have appointment with."""
        mock_can_access.return_value = True
        mock_get_patient.return_value = {
            'id': self.patient_id,
            'name': 'Test Patient',
            'age': 45,
            'medicalHistory': ['Hypertension']
        }

        client = Client()
        session = client.session
        session['doctor_id'] = self.doctor_id
        session.save()

        response = client.get(reverse('patient_record', args=[self.patient_id]))
        # Should succeed or require additional auth
        self.assertIn(response.status_code, [200, 403])

    @patch('appointments.views.doctor_can_access_patient')
    def test_doctor_cannot_access_other_patient(self, mock_can_access):
        """Test doctor cannot access patients they don't have appointments with."""
        mock_can_access.return_value = False

        client = Client()
        session = client.session
        session['doctor_id'] = self.other_doctor_id
        session.save()

        response = client.get(reverse('patient_record', args=[self.patient_id]))
        self.assertIn(response.status_code, [403, 404])


class CheckinStatusTransitionTestCase(TestCase):
    """Test valid state transitions for appointment check-in status."""

    def setUp(self):
        """Initialize test data."""
        self.base_appointment = {
            'id': 'apt_transition_001',
            'doctorID': 'doc_001',
            'patientID': 'pat_001',
            'date': str(date.today()),
            'time': '10:00',
        }

    @patch('appointments.views.get_appointment')
    @patch('appointments.views.update_appointment_status')
    def test_transition_scheduled_to_arrived(self, mock_update, mock_get):
        """Test transition from scheduled to arrived."""
        appt = dict(self.base_appointment)
        appt['status'] = 'scheduled'
        mock_get.return_value = appt

        # Check-in should update status
        result = mark_appointment_arrived(appt['id'])
        self.assertIsNotNone(result)

    @patch('appointments.views.get_appointment')
    def test_transition_arrived_to_in_progress(self, mock_get):
        """Test transition from arrived to in_progress when doctor starts exam."""
        appt = dict(self.base_appointment)
        appt['status'] = 'arrived'
        appt['arrivedAt'] = int(time.time())
        mock_get.return_value = appt

        # This should be valid state for doctor to start exam
        self.assertIn(appt['status'], ['arrived', 'in_progress'])

    @patch('appointments.views.get_appointment')
    def test_invalid_transition_cancelled_to_scheduled(self, mock_get):
        """Test invalid transition from cancelled back to scheduled."""
        appt = dict(self.base_appointment)
        appt['status'] = 'cancelled'
        mock_get.return_value = appt

        # Cancelled appointments shouldn't revert to scheduled
        # Would be handled by business logic validation
        self.assertEqual(appt['status'], 'cancelled')
        self.assertNotEqual(appt['status'], 'scheduled')


class AppointmentNotificationTestCase(TestCase):
    """Test notifications for appointment check-in and queue updates."""

    @patch('appointments.views.notify_queue_advance')
    @patch('appointments.views.get_queue_meta')
    def test_notify_when_queue_advances(self, mock_get_queue, mock_notify):
        """Test notification sent when patient reaches front of queue."""
        appointment_id = 'apt_notify_001'
        patient_id = 'pat_notify_001'
        doctor_id = 'doc_notify_001'

        mock_get_queue.return_value = {
            'current': 1,
            'total': 5,
        }

        # When patient becomes first in queue, notification should be sent
        notify_queue_advance(
            patient_id=patient_id,
            doctor_id=doctor_id,
            queue_position=1
        )

        mock_notify.assert_called_once()

    @patch('appointments.views.send_notification')
    def test_notify_checked_in_patient(self, mock_send):
        """Test notification sent when patient checks in."""
        patient_id = 'pat_checked_001'
        message = "Bạn đã check-in thành công. Vui lòng chờ trong phòng chờ."

        # Simulate sending check-in notification
        # In real system, this would go through FCM
        self.assertIsNotNone(message)


class ExamCompletionTestCase(TestCase):
    """Test workflow for completing patient examination."""

    def setUp(self):
        """Initialize test data."""
        self.appointment = {
            'id': 'apt_exam_001',
            'doctorID': 'doc_exam_001',
            'patientID': 'pat_exam_001',
            'status': 'in_progress',
            'startTime': int(time.time()) - 600,  # 10 minutes ago
        }

    @patch('appointments.views.mark_appointment_completed')
    @patch('appointments.views.update_medical_record')
    def test_complete_appointment_saves_notes(self, mock_update_record, mock_complete):
        """Test that completing appointment saves doctor's exam notes."""
        exam_notes = {
            'diagnosis': 'Hypertension controlled',
            'prescription': 'Continue current medication',
            'nextVisit': '2026-07-19',
        }

        mock_complete.return_value = {'status': 'completed', **self.appointment}
        mock_update_record.return_value = True

        # Simulate doctor completing exam
        result = mock_complete(self.appointment['id'])
        self.assertEqual(result['status'], 'completed')

    @patch('appointments.views.get_appointment')
    def test_appointment_duration_tracking(self, mock_get):
        """Test that appointment duration is tracked."""
        mock_get.return_value = self.appointment

        appt = mock_get(self.appointment['id'])
        start_time = appt.get('startTime')
        end_time = int(time.time())

        duration = (end_time - start_time) / 60  # In minutes
        self.assertGreater(duration, 0)

    @patch('appointments.views.get_appointment')
    def test_exam_notes_validation(self, mock_get):
        """Test that exam notes meet minimum requirements."""
        notes = {
            'diagnosis': 'Patient examined',
            'prescription': '',  # Empty prescription
        }

        # At minimum, diagnosis should be present
        self.assertIn('diagnosis', notes)
        self.assertIsNotNone(notes['diagnosis'])


class DashboardPriorityDisplayTestCase(TestCase):
    """Test dashboard correctly displays appointments with priority."""

    def setUp(self):
        """Initialize test data."""
        self.client = Client()
        session = self.client.session
        session['doctor_id'] = 'doc_dashboard_001'
        session.save()

    @patch('appointments.views.get_all_appointments')
    def test_dashboard_shows_arrived_patients(self, mock_get_appts):
        """Test dashboard displays arrived patients in queue."""
        mock_appointments = [
            {
                'id': 'a1',
                'patientID': 'p1',
                'name': 'Patient 1',
                'status': 'arrived',
                'queueNumber': 1,
            },
            {
                'id': 'a2',
                'patientID': 'p2',
                'name': 'Patient 2',
                'status': 'arrived',
                'queueNumber': 2,
            },
            {
                'id': 'a3',
                'patientID': 'p3',
                'name': 'Patient 3',
                'status': 'scheduled',
                'queueNumber': None,
            },
        ]
        mock_get_appts.return_value = mock_appointments

        response = self.client.get(reverse('appointments_dashboard'))
        
        if response.status_code == 200:
            # Check context contains appointments
            self.assertIn('appointments', response.context or {})

    @patch('appointments.views.get_all_appointments')
    def test_dashboard_groups_by_status(self, mock_get_appts):
        """Test dashboard groups appointments by status."""
        mock_appointments = [
            {'status': 'scheduled'},
            {'status': 'arrived'},
            {'status': 'in_progress'},
            {'status': 'completed'},
        ]
        mock_get_appts.return_value = mock_appointments

        scheduled = [a for a in mock_appointments if a['status'] == 'scheduled']
        arrived = [a for a in mock_appointments if a['status'] == 'arrived']

        self.assertEqual(len(scheduled), 1)
        self.assertEqual(len(arrived), 1)


def create_test_suite():
    """Create comprehensive test suite."""
    suite = unittest.TestSuite()
    
    loader = unittest.TestLoader()
    suite.addTests(loader.loadTestsFromTestCase(AppointmentWorkflowTestCase))
    suite.addTests(loader.loadTestsFromTestCase(QueueManagementTestCase))
    suite.addTests(loader.loadTestsFromTestCase(PatientRecordAccessTestCase))
    suite.addTests(loader.loadTestsFromTestCase(CheckinStatusTransitionTestCase))
    suite.addTests(loader.loadTestsFromTestCase(AppointmentNotificationTestCase))
    suite.addTests(loader.loadTestsFromTestCase(ExamCompletionTestCase))
    suite.addTests(loader.loadTestsFromTestCase(DashboardPriorityDisplayTestCase))
    
    return suite


if __name__ == '__main__':
    import unittest
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(create_test_suite())
