"""
Admin FHIR Export View
Provides a web interface for admins to export the Firebase RTDB data
to HL7 FHIR R4 standard format.
"""
import json
import sys
import os
from datetime import datetime

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods

# Add scripts directory to path so we can import the export module
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
from export_fhir import convert_to_fhir, clean_empty_fields

from services.firebase import db


def _admin_required(request):
    """Check if user is authenticated as admin."""
    if not request.session.get('admin_portal_user_id'):
        messages.error(request, 'Vui lòng đăng nhập admin để truy cập chức năng này.')
        return redirect('login')
    return None


def admin_fhir_export_view(request):
    """Render the FHIR export admin page."""
    guard = _admin_required(request)
    if guard:
        return guard

    context = {
        'page_title': 'Xuất dữ liệu FHIR R4',
    }
    return render(request, 'doctors/admin_fhir_export.html', context)


@require_http_methods(["POST"])
def admin_fhir_export_execute(request):
    """
    Execute the FHIR export: fetch all data from Firebase RTDB,
    convert to FHIR R4 Bundle, and return as downloadable JSON.
    """
    guard = _admin_required(request)
    if guard:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        # Fetch all data from Firebase RTDB
        db_data = db.get() or {}

        # Convert to FHIR R4 using the existing export logic
        fhir_bundle = convert_to_fhir(db_data)

        # Count resources for summary
        resource_counts = {}
        for entry in fhir_bundle.get("entry", []):
            res_type = entry.get("resource", {}).get("resourceType")
            resource_counts[res_type] = resource_counts.get(res_type, 0) + 1

        total_resources = len(fhir_bundle.get("entry", []))

        # Return as downloadable JSON file
        export_format = request.POST.get('format', 'download')

        if export_format == 'preview':
            # Return summary + first few entries for preview
            preview_bundle = {
                "resourceType": fhir_bundle["resourceType"],
                "id": fhir_bundle["id"],
                "type": fhir_bundle["type"],
                "timestamp": fhir_bundle["timestamp"],
                "total": total_resources,
                "entry": fhir_bundle["entry"][:10]  # First 10 for preview
            }
            return JsonResponse({
                'success': True,
                'summary': {
                    'total_resources': total_resources,
                    'resource_counts': resource_counts,
                    'bundle_id': fhir_bundle.get('id'),
                    'timestamp': fhir_bundle.get('timestamp'),
                },
                'preview': preview_bundle,
            }, json_dumps_params={'ensure_ascii': False, 'indent': 2})

        # Full download
        json_content = json.dumps(fhir_bundle, indent=2, ensure_ascii=False)
        filename = f"fhir_r4_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        response = HttpResponse(json_content, content_type='application/fhir+json; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(json_content.encode('utf-8'))
        return response

    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'success': False,
        }, status=500)


@require_http_methods(["POST"])
def admin_fhir_export_summary(request):
    """
    Quick summary of what will be exported without generating the full bundle.
    Fetches counts from Firebase to give the admin an overview.
    """
    guard = _admin_required(request)
    if guard:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        # Fetch shallow counts from Firebase
        hospitals = db.child("hospitals").get() or {}
        specialties = db.child("specialties").get() or {}
        doctors = db.child("doctors").get() or {}
        patients = db.child("patients").get() or {}
        health_info = db.child("health_info").get() or {}
        appointments = db.child("appointments").get() or {}
        appointment_new = db.child("appointment_new").get() or {}
        medical_records = db.child("medicalRecord").get() or db.child("medicalRecords").get() or {}

        # Count appointment_new entries
        new_apt_count = 0
        for date_key, date_node in appointment_new.items():
            if isinstance(date_node, dict):
                new_apt_count += len(date_node)

        # Count medical records
        record_count = 0
        for pat_id, pat_records in medical_records.items():
            if isinstance(pat_records, dict):
                record_count += len(pat_records)

        summary = {
            'hospitals': len(hospitals),
            'specialties': len(specialties),
            'doctors': len(doctors),
            'patients': len(patients),
            'health_info': len(health_info),
            'appointments_old': len(appointments),
            'appointments_new': new_apt_count,
            'medical_records': record_count,
        }

        return JsonResponse({
            'success': True,
            'summary': summary,
        })

    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'success': False,
        }, status=500)
