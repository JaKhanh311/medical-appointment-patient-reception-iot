from datetime import date
from urllib.parse import urlencode
from django.contrib import messages
from django.shortcuts import render, redirect

from services.RTDB_utils import (
    create_walk_in_appointment,
    create_walk_in_patient,
    get_doctor_by_id,
    get_patient_by_id,
    get_specialty_by_id,
)


def _clean_value(value):
    return (value or "").strip()


def _session_from_time(time_value):
    try:
        hour = int(str(time_value).strip().split(":")[0])
    except Exception:
        return "other"

    if 7 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    return "other"


def _build_initial_form_data(request):
    return {
        "name": "",
        "nickname": "",
        "birthdate": "",
        "gender": "",
        "phone": "",
        "email": "",
        "address": "",
        "occupation": "",
        "nationality": "",
        "ethnicity": "",
        "identity_number": "",
        "role": "self",
        "priority_group": "",
        "medical_history": "",
        "appointment_date": date.today().isoformat(),
        "appointment_time": "",
        "reason": "",
        "notes": "",
        "booking_type": "walk-in",
        "international": "",
        "location": "",
        "status": "scheduled",
        "doctor_id": request.session.get("doctor_id", ""),
    }


def add_patient_view(request):
    if request.session.get("admin_portal_user_id"):
        return redirect("admin_portal_dashboard")

    doctor_id = request.session.get("doctor_id")
    if not doctor_id:
        return redirect("login")

    doctor = get_doctor_by_id(doctor_id) or {}
    specialty = get_specialty_by_id(doctor.get("specialtyID", "")) if doctor else {}
    specialty = specialty or {}

    form_data = _build_initial_form_data(request)
    form_data["doctor_id"] = doctor_id
    form_data["location"] = _clean_value(doctor.get("hospitalID", ""))

    selected_patient = None
    selected_patient_id = _clean_value(request.GET.get("patient_id"))
    if selected_patient_id:
        selected_patient = get_patient_by_id(selected_patient_id)
        if not selected_patient:
            messages.error(request, "Không tìm thấy bệnh nhân đã tạo. Vui lòng tạo lại.")
            selected_patient_id = ""

    if selected_patient:
        form_data.update({
            "name": _clean_value(selected_patient.get("name")),
            "nickname": _clean_value(selected_patient.get("nickname")),
            "birthdate": _clean_value(selected_patient.get("birthdate")),
            "gender": _clean_value(selected_patient.get("gender")),
            "phone": _clean_value(selected_patient.get("phone")),
            "email": _clean_value(selected_patient.get("email")),
            "address": _clean_value(selected_patient.get("address")),
            "occupation": _clean_value(selected_patient.get("occupation")),
            "nationality": _clean_value(selected_patient.get("nationality")),
            "ethnicity": _clean_value(selected_patient.get("ethnicity")),
            "identity_number": _clean_value(selected_patient.get("identityNumber")),
            "role": _clean_value(selected_patient.get("role")) or "self",
            "priority_group": _clean_value(selected_patient.get("priorityGroup")),
            "medical_history": _clean_value(selected_patient.get("medical_history")),
        })

    if request.method == "POST":
        form_action = _clean_value(request.POST.get("form_action"))

        form_data.update({
            "name": _clean_value(request.POST.get("name")),
            "nickname": _clean_value(request.POST.get("nickname")),
            "birthdate": _clean_value(request.POST.get("birthdate")),
            "gender": _clean_value(request.POST.get("gender")),
            "phone": _clean_value(request.POST.get("phone")),
            "email": _clean_value(request.POST.get("email")),
            "address": _clean_value(request.POST.get("address")),
            "occupation": _clean_value(request.POST.get("occupation")),
            "nationality": _clean_value(request.POST.get("nationality")),
            "ethnicity": _clean_value(request.POST.get("ethnicity")),
            "identity_number": _clean_value(request.POST.get("identity_number")),
            "role": _clean_value(request.POST.get("role")) or "self",
            "priority_group": _clean_value(request.POST.get("priority_group")),
            "medical_history": _clean_value(request.POST.get("medical_history")),
            "appointment_date": _clean_value(request.POST.get("appointment_date")),
            "appointment_time": _clean_value(request.POST.get("appointment_time")),
            "reason": _clean_value(request.POST.get("reason")),
            "notes": _clean_value(request.POST.get("notes")),
            "booking_type": _clean_value(request.POST.get("booking_type")) or "walk-in",
            "international": request.POST.get("international", ""),
            "location": _clean_value(request.POST.get("location")),
            "status": _clean_value(request.POST.get("status")) or "scheduled",
            "doctor_id": doctor_id,
        })
        selected_patient_id = _clean_value(request.POST.get("patient_id")) or selected_patient_id
        if selected_patient_id:
            selected_patient = get_patient_by_id(selected_patient_id)

        if form_action == "create_patient":
            errors = []
            if not form_data["name"]:
                errors.append("Vui lòng nhập họ tên bệnh nhân.")
            if not form_data["birthdate"]:
                errors.append("Vui lòng nhập ngày sinh.")
            if not form_data["gender"]:
                errors.append("Vui lòng chọn giới tính.")
            if not form_data["phone"]:
                errors.append("Vui lòng nhập số điện thoại.")

            if errors:
                for error_message in errors:
                    messages.error(request, error_message)
                return render(
                    request,
                    "patients/add_patient.html",
                    {
                        "form_data": form_data,
                        "doctor": doctor,
                        "specialty": specialty,
                        "selected_patient": selected_patient,
                    },
                )

            created_patient = create_walk_in_patient(
                {
                    "name": form_data["name"],
                    "nickname": form_data["nickname"],
                    "birthdate": form_data["birthdate"],
                    "gender": form_data["gender"],
                    "phone": form_data["phone"],
                    "email": form_data["email"],
                    "address": form_data["address"],
                    "occupation": form_data["occupation"],
                    "nationality": form_data["nationality"],
                    "ethnicity": form_data["ethnicity"],
                    "identity_number": form_data["identity_number"],
                    "role": form_data["role"],
                    "priority_group": form_data["priority_group"],
                    "medical_history": form_data["medical_history"],
                }
            )

            if not created_patient:
                messages.error(request, "Không thể tạo hồ sơ bệnh nhân trên Firebase.")
                return render(
                    request,
                    "patients/add_patient.html",
                    {
                        "form_data": form_data,
                        "doctor": doctor,
                        "specialty": specialty,
                        "selected_patient": selected_patient,
                    },
                )

            messages.success(request, "Đã lưu hồ sơ bệnh nhân. Tiếp tục bước 2 để đặt lịch khám.")
            next_query = urlencode({"patient_id": _clean_value(created_patient.get("patientID"))})
            return redirect(f"/appointments/create/?{next_query}")

        if form_action == "create_appointment":
            errors = []
            if not selected_patient_id:
                errors.append("Vui lòng hoàn tất bước 1: tạo bệnh nhân trước.")
            if not form_data["appointment_date"]:
                errors.append("Vui lòng chọn ngày khám.")
            if not form_data["appointment_time"]:
                errors.append("Vui lòng chọn giờ khám.")
            if not form_data["reason"]:
                errors.append("Vui lòng nhập lý do khám.")

            if errors:
                for error_message in errors:
                    messages.error(request, error_message)
                return render(
                    request,
                    "patients/add_patient.html",
                    {
                        "form_data": form_data,
                        "doctor": doctor,
                        "specialty": specialty,
                        "selected_patient": selected_patient,
                    },
                )

            created_appointment = create_walk_in_appointment(
                {
                    "date": form_data["appointment_date"],
                    "time": form_data["appointment_time"],
                    "session": _session_from_time(form_data["appointment_time"]),
                    "doctor_id": doctor_id,
                    "doctor_name": _clean_value(doctor.get("name", "")),
                    "specialty_id": _clean_value(doctor.get("specialtyID", "")),
                    "specialty_name": _clean_value(specialty.get("name", "")),
                    "patient_id": selected_patient_id,
                    "status": form_data["status"],
                    "reason": form_data["reason"],
                    "notes": form_data["notes"],
                    "location": form_data["location"],
                    "international": bool(form_data["international"]),
                    "booking_type": form_data["booking_type"],
                    "user_id": _clean_value((selected_patient or {}).get("userID")) or selected_patient_id,
                }
            )

            if not created_appointment:
                messages.error(request, "Không thể tạo lịch khám cho bệnh nhân.")
                return render(
                    request,
                    "patients/add_patient.html",
                    {
                        "form_data": form_data,
                        "doctor": doctor,
                        "specialty": specialty,
                        "selected_patient": selected_patient,
                    },
                )

            messages.success(request, "Đã đặt lịch khám thành công cho bệnh nhân.")
            form_data["appointment_time"] = ""
            form_data["reason"] = ""
            form_data["notes"] = ""
            return render(
                request,
                "patients/add_patient.html",
                {
                    "form_data": form_data,
                    "doctor": doctor,
                    "specialty": specialty,
                    "selected_patient": selected_patient,
                },
            )

    return render(
        request,
        "patients/add_patient.html",
        {
            "form_data": form_data,
            "doctor": doctor,
            "specialty": specialty,
            "selected_patient": selected_patient,
        },
    )
