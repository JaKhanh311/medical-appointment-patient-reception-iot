from django.urls import path
from .views import add_patient_view

urlpatterns = [
    path('add/', add_patient_view, name='add_patient'),
]
