from django.urls import path
from .views import (
    home_view,
    news_list_view,
    login_view,
    logout_view,
    admin_portal_login_view,
    admin_portal_dashboard_view,
    admin_portal_logout_view,
    admin_doctor_add_view,
    admin_doctor_edit_view,
    admin_doctor_history_view,
    admin_doctor_provision_view,
    admin_statistics_view,
)
from .views_fhir_export import (
    admin_fhir_export_view,
    admin_fhir_export_execute,
    admin_fhir_export_summary,
)

urlpatterns = [
    path('', home_view, name='home'),
    path('news/', news_list_view, name='news_list'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('admin-portal/login/', admin_portal_login_view, name='admin_portal_login'),
    path('admin-portal/', admin_portal_dashboard_view, name='admin_portal_dashboard'),
    path('admin-portal/logout/', admin_portal_logout_view, name='admin_portal_logout'),
    path('admin-portal/fhir-export/', admin_fhir_export_view, name='admin_fhir_export'),
    path('admin-portal/fhir-export/execute/', admin_fhir_export_execute, name='admin_fhir_export_execute'),
    path('admin-portal/fhir-export/summary/', admin_fhir_export_summary, name='admin_fhir_export_summary'),
    path('admin-doctors/add/', admin_doctor_add_view, name='admin_doctor_add'),
    path('admin-doctors/<str:doctor_id>/edit/', admin_doctor_edit_view, name='admin_doctor_edit'),
    path('admin-doctors/<str:doctor_id>/history/', admin_doctor_history_view, name='admin_doctor_history'),
    path('admin-doctors/provision/', admin_doctor_provision_view, name='admin_doctor_provision'),
    path('admin-portal/statistics/', admin_statistics_view, name='admin_statistics'),
]
