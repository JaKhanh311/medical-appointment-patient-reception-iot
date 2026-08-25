from django.test import Client, TestCase
from django.urls import reverse


class PortalRoutingTests(TestCase):
	def setUp(self):
		self.client = Client()

	def test_doctor_login_page_is_public(self):
		response = self.client.get(reverse('login'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Cổng bác sĩ')

	def test_admin_login_page_is_public(self):
		response = self.client.get(reverse('admin_portal_login'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Cổng quản trị')

	def test_admin_pages_redirect_to_admin_login_when_logged_out(self):
		response = self.client.get(reverse('admin_doctor_add'))

		self.assertRedirects(response, reverse('admin_portal_login'))

	def test_admin_session_redirected_away_from_doctor_login(self):
		session = self.client.session
		session['admin_portal_user_id'] = 'admin-1'
		session.save()

		response = self.client.get(reverse('login'))

		self.assertRedirects(response, reverse('admin_portal_dashboard'), fetch_redirect_response=False)

	def test_doctor_session_redirected_away_from_admin_login(self):
		session = self.client.session
		session['doctor_id'] = 'doctor-1'
		session.save()

		response = self.client.get(reverse('admin_portal_login'))

		self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)

	def test_admin_session_redirected_away_from_doctor_dashboard(self):
		session = self.client.session
		session['admin_portal_user_id'] = 'admin-1'
		session.save()

		response = self.client.get(reverse('dashboard'))

		self.assertRedirects(response, reverse('admin_portal_dashboard'), fetch_redirect_response=False)
