from django.shortcuts import redirect
from django.urls import reverse


class DoctorAuthMiddleware:
    """Middleware to check if doctor is logged in"""

    def __init__(self, get_response):
        self.get_response = get_response
        # Cache resolved URLs at init time (they don't change at runtime)
        self._home_url = reverse('home')
        self._news_list_url = reverse('news_list')
        self._doctor_login_url = reverse('login')
        self._admin_login_url = reverse('admin_portal_login')
        self._doctor_dashboard_url = reverse('dashboard')
        self._admin_dashboard_url = reverse('admin_portal_dashboard')
        self._public_exact_urls = {self._home_url, self._news_list_url}

    def __call__(self, request):
        current_path = request.path_info

        # Early return for static/media — no auth check needed
        if current_path.startswith(('/static/', '/media/', '/admin/')):
            return self.get_response(request)

        is_doctor_logged_in = 'doctor_id' in request.session
        is_admin_logged_in = 'admin_portal_user_id' in request.session
        is_admin_manage_path = current_path.startswith('/admin-doctors/')

        if current_path.startswith(self._admin_login_url):
            if is_admin_logged_in:
                return redirect(self._admin_dashboard_url)
            if is_doctor_logged_in:
                return redirect(self._doctor_dashboard_url)
            return self.get_response(request)

        if current_path.startswith('/admin-portal/'):
            if not is_admin_logged_in:
                if is_doctor_logged_in:
                    return redirect(self._doctor_dashboard_url)
                return redirect('admin_portal_login')
            return self.get_response(request)

        if is_admin_manage_path:
            if not is_admin_logged_in:
                if is_doctor_logged_in:
                    return redirect(self._doctor_dashboard_url)
                return redirect('admin_portal_login')
            return self.get_response(request)

        if current_path.startswith(self._doctor_login_url):
            if is_doctor_logged_in:
                return redirect(self._doctor_dashboard_url)
            if is_admin_logged_in:
                return redirect(self._admin_dashboard_url)
            return self.get_response(request)

        is_public_exact_path = current_path in self._public_exact_urls
        is_doctor_dashboard_path = current_path.startswith(self._doctor_dashboard_url)

        if is_doctor_dashboard_path and not is_doctor_logged_in:
            if is_admin_logged_in:
                return redirect(self._admin_dashboard_url)
            return redirect('login')

        if not is_public_exact_path and not is_doctor_dashboard_path and not is_doctor_logged_in:
            if is_admin_logged_in:
                return redirect(self._admin_dashboard_url)
            return redirect('login')

        response = self.get_response(request)
        return response