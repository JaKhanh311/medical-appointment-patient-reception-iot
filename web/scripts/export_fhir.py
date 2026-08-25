#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
FHIR Export Script for Doctor Portal Project
Converts database export (JSON) to HL7 FHIR Release 4 (R4) resources.
Refined to fix terminology, semantic model, fullUrl consistency, explicit nulls,
and other compliance issues highlighted during validation.
"""

import json
import os
import sys
from datetime import datetime

# Real SNOMED CT codes for specialties mapping
SPECIALTY_SNOMED_MAP = {
    "spec_001": {"code": "394583002", "display": "Endocrinology", "vi": "Khoa Nội Tiết"},
    "spec_002": {"code": "394807007", "display": "Pediatric specialty", "vi": "Khoa Nhi"},
    "spec_003": {"code": "394597005", "display": "Ophthalmology", "vi": "Khoa Mắt"},
    "spec_004": {"code": "394604002", "display": "Otorhinolaryngology / ENT surgery", "vi": "Khoa Tai Mũi Họng"},
    "spec_005": {"code": "394811005", "display": "Geriatric medicine", "vi": "Khoa Lão Khoa"},
    "spec_006": {"code": "394585005", "display": "Obstetrics and gynecology", "vi": "Khoa Sản Phụ Khoa"},
    "spec_007": {"code": "394579002", "display": "Cardiology", "vi": "Khoa Tim Mạch"},
    "spec_008": {"code": "418112009", "display": "Pulmonary medicine", "vi": "Khoa Hô Hấp"},
    "spec_009": {"code": "394582007", "display": "Dermatology", "vi": "Khoa Da Liễu"},
    "spec_010": {"code": "394584008", "display": "Gastroenterology", "vi": "Khoa Tiêu Hóa"},
    "spec_011": {"code": "394591004", "display": "Neurology", "vi": "Khoa Thần Kinh"},
    "spec_012": {"code": "394587001", "display": "Psychiatry", "vi": "Khoa Tâm Thần"},
    "spec_013": {"code": "394609007", "display": "General surgery", "vi": "Khoa Phẫu Thuật"},
    "spec_014": {"code": "394801008", "display": "Orthopedic surgery", "vi": "Khoa Xương Khớp"},
    "spec_015": {"code": "394803006", "display": "Clinical hematology", "vi": "Khoa Huyết Học"},
    "spec_016": {"code": "416314002", "display": "Emergency medicine", "vi": "Khoa Cấp Cứu"},
    "spec_017": {"code": "722163006", "display": "Dentistry", "vi": "Khoa Nha Khoa"},
    "spec_018": {"code": "394593009", "display": "Clinical oncology", "vi": "Khoa Ung Thư"},
    "spec_019": {"code": "394589003", "display": "Nephrology", "vi": "Khoa Thận - Tiết Niệu"},
    "spec_020": {"code": "394802001", "display": "Clinical immunology", "vi": "Khoa Dị Ứng - Miễn Dịch"}
}

def format_date(raw_date):
    """Parse date from DD/MM/YYYY or YYYY-MM-DD to YYYY-MM-DD"""
    if not raw_date:
        return None
    raw_date = str(raw_date).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw_date, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw_date

def format_gender(raw_gender):
    """Normalize gender to FHIR R4 values: male, female, other, unknown"""
    if not raw_gender:
        return "unknown"
    g = str(raw_gender).lower().strip()
    if g in ("male", "nam", "m"):
        return "male"
    elif g in ("female", "nữ", "nu", "f"):
        return "female"
    elif g in ("other", "khác"):
        return "other"
    return "unknown"

def parse_iso_datetime(date_str, time_str=None, session=None):
    """Construct an ISO-8601 string for start times (Vietnam GMT+7)"""
    d = format_date(date_str)
    if not d:
        return None
    
    t = "08:00:00"
    if time_str:
        time_str = str(time_str).strip()
        parts = time_str.split(":")
        if len(parts) >= 2:
            try:
                hour = int(parts[0])
                minute = int(parts[1])
                t = f"{hour:02d}:{minute:02d}:00"
            except ValueError:
                pass
    elif session:
        session = str(session).lower().strip()
        if session == "afternoon":
            t = "14:00:00"
        elif session == "morning":
            t = "08:00:00"
            
    return f"{d}T{t}+07:00"

def clean_empty_fields(val):
    """
    Recursively remove keys with None, empty lists, empty dicts, or empty strings
    to prevent explicit nulls and comply with standard FHIR validators.
    """
    if isinstance(val, dict):
        cleaned = {}
        for k, v in val.items():
            cleaned_v = clean_empty_fields(v)
            if cleaned_v is not None and cleaned_v != "" and cleaned_v != [] and cleaned_v != {}:
                cleaned[k] = cleaned_v
        return cleaned if cleaned else None
    elif isinstance(val, list):
        cleaned = []
        for item in val:
            cleaned_item = clean_empty_fields(item)
            if cleaned_item is not None and cleaned_item != "" and cleaned_item != [] and cleaned_item != {}:
                cleaned.append(cleaned_item)
        return cleaned if cleaned else None
    else:
        return val

def make_standard_observation(obs_id, status, category, code, subject_ref, encounter_ref, effective_dt):
    """Construct standard base for FHIR R4 Observation resource"""
    return {
        "resourceType": "Observation",
        "id": obs_id,
        "meta": {
            "profile": ["http://hl7.org/fhir/StructureDefinition/Observation"]
        },
        "status": status,
        "category": category,
        "code": code,
        "subject": subject_ref,
        "encounter": encounter_ref,
        "effectiveDateTime": effective_dt
    }

def convert_to_fhir(db_data):
    """
    Convert Firebase Realtime DB export to FHIR R4 resources,
    applying strict validation rules (resolving SNOMED codes, eliminating nulls,
    linking HealthcareServices dynamically).
    """
    fhir_resources = []
    
    hospitals = db_data.get("hospitals", {})
    specialties = db_data.get("specialties", {})
    doctors = db_data.get("doctors", {})
    patients = db_data.get("patients", {})
    health_info_dict = db_data.get("health_info", {})
    
    # 1. Map Hospitals -> FHIR Organization
    for hosp_id, hosp in hospitals.items():
        org = {
            "resourceType": "Organization",
            "id": hosp_id,
            "meta": {
                "profile": ["http://hl7.org/fhir/StructureDefinition/Organization"]
            },
            "active": hosp.get("isActive", True),
            "name": hosp.get("fullName", hosp.get("name", "Unknown Hospital")),
            "alias": [hosp.get("name")] if hosp.get("name") else [],
            "description": hosp.get("description"),
            "contact": []
        }
        
        telecoms = []
        if hosp.get("phone"):
            telecoms.append({"system": "phone", "value": hosp.get("phone"), "use": "work"})
        if hosp.get("email"):
            telecoms.append({"system": "email", "value": hosp.get("email"), "use": "work"})
        if hosp.get("website"):
            telecoms.append({"system": "url", "value": hosp.get("website"), "use": "work"})
            
        address_val = None
        if hosp.get("address"):
            address_val = {
                "use": "work",
                "type": "both",
                "text": hosp.get("address"),
                "country": "Vietnam"
            }
            
        if telecoms or address_val:
            org["contact"].append({
                "telecom": telecoms,
                "address": address_val
            })
            
        fhir_resources.append(org)

    # 2. Map Active Hospital-Specialty Pairs -> FHIR HealthcareService
    # Dynamically links services to the actual providing hospitals
    active_hcs_pairs = set()
    for doc_id, doc in doctors.items():
        hosp_id = doc.get("hospitalID") or "hosp_A"
        spec_id = doc.get("specialtyID")
        if spec_id:
            active_hcs_pairs.add((hosp_id, spec_id))
            
    for hosp_id, spec_id in sorted(active_hcs_pairs):
        spec = specialties.get(spec_id, {})
        hosp = hospitals.get(hosp_id, {})
        hosp_name = hosp.get("fullName", hosp.get("name", "Hospital"))
        
        hcs_id = f"{hosp_id}-{spec_id}"
        
        hcs = {
            "resourceType": "HealthcareService",
            "id": hcs_id,
            "meta": {
                "profile": ["http://hl7.org/fhir/StructureDefinition/HealthcareService"]
            },
            "active": True,
            "providedBy": {
                "reference": f"Organization/{hosp_id}",
                "display": hosp_name
            },
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/service-category",
                    "code": "30",
                    "display": "Specialist Clinical Physician"
                }]
            }],
            "type": [{
                "coding": [{
                    "system": "https://doctorportal.vn/fhir/CodeSystem/specialty-types",
                    "code": spec_id,
                    "display": spec.get("name")
                }],
                "text": spec.get("name")
            }],
            "name": f"{spec.get('name')} - {hosp_name}",
            "comment": spec.get("description")
        }
        
        if spec_id in SPECIALTY_SNOMED_MAP:
            mapped = SPECIALTY_SNOMED_MAP[spec_id]
            hcs["specialty"] = [{
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": mapped["code"],
                    "display": mapped["display"]
                }],
                "text": mapped["vi"]
            }]
            
        if spec.get("phone"):
            hcs["telecom"] = [{
                "system": "phone",
                "value": spec.get("phone"),
                "use": "work"
            }]
            
        fhir_resources.append(hcs)

    # 3. Map Doctors -> FHIR Practitioner and PractitionerRole
    for doc_id, doc in doctors.items():
        prac = {
            "resourceType": "Practitioner",
            "id": doc_id,
            "meta": {
                "profile": ["http://hl7.org/fhir/StructureDefinition/Practitioner"]
            },
            "active": doc.get("isActive", True),
            "name": [{
                "use": "official",
                "text": doc.get("name"),
                "prefix": [doc.get("title")] if doc.get("title") else []
            }],
            "telecom": [],
            "gender": format_gender(doc.get("gender")),
            "birthDate": format_date(doc.get("dateOfBirth")),
            "photo": [],
            "qualification": []
        }
        
        if doc.get("phone"):
            prac["telecom"].append({"system": "phone", "value": doc.get("phone"), "use": "mobile"})
        if doc.get("email"):
            prac["telecom"].append({"system": "email", "value": doc.get("email"), "use": "work"})
            
        if doc.get("avatarUrl"):
            prac["photo"].append({
                "url": doc.get("avatarUrl"),
                "title": "Avatar"
            })
            
        # Standardize qualifications as plain text in code.text to handle synthetic data inconsistencies gracefully
        if doc.get("certifications"):
            prac["qualification"].append({
                "code": {
                    "text": doc.get("certifications")
                }
            })
        if doc.get("education"):
            prac["qualification"].append({
                "code": {
                    "text": doc.get("education")
                }
            })
            
        fhir_resources.append(prac)
        
        # PractitionerRole
        spec_id = doc.get("specialtyID")
        hosp_id = doc.get("hospitalID") or "hosp_A"
        
        role = {
            "resourceType": "PractitionerRole",
            "id": f"{doc_id}-role",
            "meta": {
                "profile": ["http://hl7.org/fhir/StructureDefinition/PractitionerRole"]
            },
            "active": doc.get("isActive", True),
            "practitioner": {
                "reference": f"Practitioner/{doc_id}",
                "display": doc.get("name")
            },
            "organization": {
                "reference": f"Organization/{hosp_id}"
            },
            "healthcareService": [
                {
                    "reference": f"HealthcareService/{hosp_id}-{spec_id}"
                }
            ] if spec_id else []
        }
        
        if spec_id in SPECIALTY_SNOMED_MAP:
            mapped = SPECIALTY_SNOMED_MAP[spec_id]
            role["specialty"] = [{
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": mapped["code"],
                    "display": mapped["display"]
                }],
                "text": mapped["vi"]
            }]
            
        fhir_resources.append(role)

    # 4. Map Patients -> FHIR Patient + Allergies + Observations
    patient_map = {}
    for pat_id, pat in patients.items():
        pat_fhir_id = pat_id
        patient_map[pat_id] = pat.get("name", "Unknown Patient")
        
        patient_res = {
            "resourceType": "Patient",
            "id": pat_fhir_id,
            "meta": {
                "profile": ["http://hl7.org/fhir/StructureDefinition/Patient"]
            },
            "active": True,
            "name": [{
                "use": "official",
                "text": pat.get("name")
            }],
            "telecom": [],
            "gender": format_gender(pat.get("gender")),
            "birthDate": format_date(pat.get("birthdate")),
            "address": [],
            "photo": [],
            "extension": []
        }
        
        if pat.get("phone"):
            patient_res["telecom"].append({"system": "phone", "value": pat.get("phone"), "use": "mobile"})
        if pat.get("email"):
            patient_res["telecom"].append({"system": "email", "value": pat.get("email"), "use": "home"})
            
        if pat.get("avatarBase64"):
            patient_res["photo"].append({
                "contentType": "image/png",
                "data": pat.get("avatarBase64"),
                "title": "Avatar"
            })
            
        if pat.get("identityNumber"):
            patient_res["identifier"] = [{
                "use": "official",
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "NI",
                        "display": "National Identifier"
                    }],
                    "text": "National Identifier"
                },
                "system": "http://hl7.org/fhir/sid/passport-vietnam",
                "value": pat.get("identityNumber")
            }]
            
        if pat.get("healthInsurance"):
            parts = pat.get("healthInsurance").split("|")
            card_id = parts[0]
            if "identifier" not in patient_res:
                patient_res["identifier"] = []
            patient_res["identifier"].append({
                "use": "official",
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "MC",
                        "display": "Patient's Member Card Number"
                    }],
                    "text": "Vietnamese Health Insurance Card Number"
                },
                "system": "http://vietnam-bhyt.gov.vn",
                "value": card_id,
                "assigner": {"display": parts[1]} if len(parts) > 1 else None
            })
            
        if pat.get("address"):
            patient_res["address"].append({
                "use": "home",
                "type": "physical",
                "text": pat.get("address"),
                "country": "Vietnam"
            })
            
        # Standard extensions
        if pat.get("ethnicity"):
            patient_res["extension"].append({
                "url": "http://hl7.org/fhir/StructureDefinition/patient-ethnicity",
                "valueString": pat.get("ethnicity")
            })
        if pat.get("nationality"):
            patient_res["extension"].append({
                "url": "http://hl7.org/fhir/StructureDefinition/patient-nationality",
                "valueCodeableConcept": {
                    "text": pat.get("nationality")
                }
            })
        if pat.get("occupation"):
            patient_res["extension"].append({
                "url": "http://hl7.org/fhir/StructureDefinition/patient-occupation",
                "valueString": pat.get("occupation")
            })
            
        fhir_resources.append(patient_res)
        
        # Health Info -> Observations & AllergyIntolerance
        hinfo = None
        for h_id, h_val in health_info_dict.items():
            if h_val.get("patientID") == pat_id or h_id == pat.get("userID"):
                hinfo = h_val
                break
                
        if hinfo:
            created_dt = datetime.fromtimestamp(hinfo.get("createdAt", 1776844351278) / 1000).isoformat() + "+07:00"
            
            # ABO Blood type
            blood_type = hinfo.get("bloodType")
            if blood_type:
                obs = make_standard_observation(
                    obs_id=f"{pat_fhir_id}-bloodtype",
                    status="final",
                    category=[{
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "laboratory",
                            "display": "Laboratory"
                        }]
                    }],
                    code={
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "883-9",
                            "display": "ABO and Rh group [Type] in Blood"
                        }],
                        "text": "ABO and Rh group [Type] in Blood"
                    },
                    subject_ref={"reference": f"Patient/{pat_fhir_id}"},
                    encounter_ref=None,
                    effective_dt=created_dt
                )
                obs["valueCodeableConcept"] = {
                    "text": blood_type
                }
                fhir_resources.append(obs)
                
            # Height
            height = hinfo.get("height")
            if height:
                try:
                    obs = make_standard_observation(
                        obs_id=f"{pat_fhir_id}-height",
                        status="final",
                        category=[{
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "vital-signs",
                                "display": "Vital Signs"
                            }]
                        }],
                        code={
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "8302-2",
                                "display": "Body height"
                            }]
                        },
                        subject_ref={"reference": f"Patient/{pat_fhir_id}"},
                        encounter_ref=None,
                        effective_dt=created_dt
                    )
                    obs["valueQuantity"] = {
                        "value": float(height),
                        "unit": "cm",
                        "system": "http://unitsofmeasure.org",
                        "code": "cm"
                    }
                    fhir_resources.append(obs)
                except ValueError:
                    pass
                    
            # Weight
            weight = hinfo.get("weight")
            if weight:
                try:
                    obs = make_standard_observation(
                        obs_id=f"{pat_fhir_id}-weight",
                        status="final",
                        category=[{
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "vital-signs",
                                "display": "Vital Signs"
                            }]
                        }],
                        code={
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "29463-7",
                                "display": "Body weight"
                            }]
                        },
                        subject_ref={"reference": f"Patient/{pat_fhir_id}"},
                        encounter_ref=None,
                        effective_dt=created_dt
                    )
                    obs["valueQuantity"] = {
                        "value": float(weight),
                        "unit": "kg",
                        "system": "http://unitsofmeasure.org",
                        "code": "kg"
                    }
                    fhir_resources.append(obs)
                except ValueError:
                    pass
                    
            # Social History (diet, drinking, smoking)
            for hist_type, loinc_code, display_name in [
                ("smoking", "72166-2", "Tobacco smoking status"),
                ("drinking", "74013-4", "Alcoholic drinks per day"),
                ("diet", "82290-8", "Nutritional status nutrition")
            ]:
                hist_val = hinfo.get(hist_type)
                if hist_val:
                    obs = make_standard_observation(
                        obs_id=f"{pat_fhir_id}-{hist_type}",
                        status="final",
                        category=[{
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "social-history",
                                "display": "Social History"
                            }]
                        }],
                        code={
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": loinc_code,
                                "display": display_name
                            }]
                        },
                        subject_ref={"reference": f"Patient/{pat_fhir_id}"},
                        encounter_ref=None,
                        effective_dt=created_dt
                    )
                    obs["valueCodeableConcept"] = {
                        "text": hist_val
                    }
                    fhir_resources.append(obs)
                    
            # Allergies
            allergy_fields = [
                ("drugAllergy", "medication"),
                ("foodAllergy", "food"),
                ("insectAllergy", "environment"),
                ("respiratoryAllergy", "biologic"),
                ("skinAllergy", "environment"),
                ("otherAllergy", "other")
            ]
            for field_name, category in allergy_fields:
                allergy_val = hinfo.get(field_name)
                if allergy_val and str(allergy_val).strip():
                    fhir_resources.append({
                        "resourceType": "AllergyIntolerance",
                        "id": f"{pat_fhir_id}-allergy-{field_name.lower()}",
                        "meta": {
                            "profile": ["http://hl7.org/fhir/StructureDefinition/AllergyIntolerance"]
                        },
                        "clinicalStatus": {
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                "code": "active",
                                "display": "Active"
                            }]
                        },
                        "verificationStatus": {
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                                "code": "confirmed",
                                "display": "Confirmed"
                            }]
                        },
                        "type": "allergy",
                        "category": [category],
                        "code": {
                            "text": str(allergy_val)
                        },
                        "patient": {"reference": f"Patient/{pat_fhir_id}"},
                        "recordedDate": created_dt
                    })

    # 5. Map Appointments -> FHIR Appointment
    all_apts = {}
    
    old_apts = db_data.get("appointments", {})
    for apt_id, apt in old_apts.items():
        all_apts[apt_id] = apt
        
    new_apts_root = db_data.get("appointment_new", {})
    for date_key, date_node in new_apts_root.items():
        if isinstance(date_node, dict):
            for apt_id, apt in date_node.items():
                all_apts[apt_id] = apt
                
    for apt_id, apt in all_apts.items():
        pat_id = apt.get("patientID")
        doc_id = apt.get("doctorID")
        spec_id = apt.get("specialtyID")
        spec_name = apt.get("specialtyName")
        
        status_map = {
            "scheduled": "booked",
            "cancelled": "cancelled",
            "completed": "fulfilled",
            "no_show": "noshow"
        }
        fhir_status = status_map.get(apt.get("status", "").lower(), "booked")
        
        apt_start = parse_iso_datetime(
            apt.get("date") or apt.get("appointmentDate"),
            apt.get("time"),
            apt.get("session")
        )
        
        apt_res = {
            "resourceType": "Appointment",
            "id": apt_id,
            "meta": {
                "profile": ["http://hl7.org/fhir/StructureDefinition/Appointment"]
            },
            "status": fhir_status,
            "description": f"Appointment at {apt.get('location')}" if apt.get("location") else None,
            "start": apt_start,
            "created": datetime.fromtimestamp(apt.get("createdAt", 1773642258099) / 1000).isoformat() + "+07:00" if apt.get("createdAt") else None,
            "participant": []
        }
        
        if pat_id:
            apt_res["participant"].append({
                "actor": {
                    "reference": f"Patient/{pat_id}",
                    "display": patient_map.get(pat_id)
                },
                "required": "required",
                "status": "accepted"
            })
        if doc_id:
            apt_res["participant"].append({
                "actor": {
                    "reference": f"Practitioner/{doc_id}",
                    "display": apt.get("doctorName")
                },
                "required": "required",
                "status": "accepted"
            })
            
        if spec_id:
            apt_res["serviceType"] = [{
                "coding": [{
                    "system": "https://doctorportal.vn/fhir/CodeSystem/specialty-types",
                    "code": spec_id,
                    "display": spec_name
                }],
                "text": spec_name
            }]
            
        if apt.get("reason"):
            apt_res["reasonCode"] = [{
                "text": apt.get("reason")
            }]
            
        if apt.get("notes"):
            apt_res["note"] = [{"text": apt.get("notes")}]
            
        fhir_resources.append(apt_res)

    # 6. Map Medical Records -> FHIR Encounter, Conditions, Observations, MedicationRequests
    # Hỗ trợ cả cấu trúc cũ (medicalRecords/patientID/entry) và mới (medicalRecord/doctorID/patientID/entry).
    medical_records_root = db_data.get("medicalRecord") or db_data.get("medicalRecords", {})

    # Flatten về dict {patientID: {recordID: record}} để xử lý đồng nhất
    flat_records_by_patient = {}
    if isinstance(medical_records_root, dict):
        for outer_key, outer_node in medical_records_root.items():
            if not isinstance(outer_node, dict):
                continue
            # Phát hiện cấu trúc: nếu giá trị bên trong cũng là dict-of-dict không phải record thì là cấu trúc mới
            sample = next(iter(outer_node.values()), None)
            is_new = isinstance(sample, dict) and not (sample.get("examDate") or sample.get("recordID"))
            if is_new:
                # outer_key = doctorID
                for pat_id, pat_records in outer_node.items():
                    if isinstance(pat_records, dict):
                        flat_records_by_patient.setdefault(pat_id, {}).update(pat_records)
            else:
                # outer_key = patientID
                flat_records_by_patient.setdefault(outer_key, {}).update(outer_node)

    for pat_id, pat_records in flat_records_by_patient.items():
        if not isinstance(pat_records, dict):
            continue

        for record_id, record in pat_records.items():
            doc_id = record.get("doctorID")
            apt_id = record.get("appointmentID")
            exam_date = record.get("examDate")
            exam_time = record.get("examTime")
            
            encounter_id = f"{pat_id}-{record_id}"
            encounter_start = parse_iso_datetime(exam_date, exam_time)
            
            # Encounter
            enc = {
                "resourceType": "Encounter",
                "id": encounter_id,
                "meta": {
                    "profile": ["http://hl7.org/fhir/StructureDefinition/Encounter"]
                },
                "status": "finished" if record.get("status") == "completed" else "unknown",
                "class": {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "AMB",
                    "display": "ambulatory"
                },
                "subject": {"reference": f"Patient/{pat_id}"},
                "participant": [],
                "appointment": [],
                "period": {},
                "specialArrangement": [],
                "diagnosis": []
            }
            
            if doc_id:
                enc["participant"].append({
                    "type": [{
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                            "code": "PPRF",
                            "display": "primary performer"
                        }]
                    }],
                    "individual": {"reference": f"Practitioner/{doc_id}"}
                })
                
            if encounter_start:
                enc["period"]["start"] = encounter_start
                
            if apt_id:
                enc["appointment"].append({"reference": f"Appointment/{apt_id}"})
                
            if record.get("advice"):
                enc["specialArrangement"].append({
                    "text": record.get("advice")
                })
                
            if record.get("diagnosis"):
                enc["diagnosis"].append({
                    "condition": {
                        "reference": f"Condition/{encounter_id}-diag"
                    }
                })
                
            if record.get("symptoms"):
                enc["diagnosis"].append({
                    "condition": {
                        "reference": f"Condition/{encounter_id}-sym"
                    }
                })
                
            fhir_resources.append(enc)
            
            # Diagnosis Condition
            diagnosis = record.get("diagnosis")
            if diagnosis:
                fhir_resources.append({
                    "resourceType": "Condition",
                    "id": f"{encounter_id}-diag",
                    "meta": {
                        "profile": ["http://hl7.org/fhir/StructureDefinition/Condition"]
                    },
                    "clinicalStatus": {
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                            "display": "Active"
                        }]
                    },
                    "verificationStatus": {
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/condition-verstatus",
                            "code": "confirmed",
                            "display": "Confirmed"
                        }]
                    },
                    "category": [{
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                            "code": "encounter-diagnosis",
                            "display": "Encounter Diagnosis"
                        }]
                    }],
                    "code": {"text": diagnosis},
                    "subject": {"reference": f"Patient/{pat_id}"},
                    "encounter": {"reference": f"Encounter/{encounter_id}"},
                    "recordedDate": encounter_start
                })
                
            # Symptoms Condition
            symptoms = record.get("symptoms")
            if symptoms:
                fhir_resources.append({
                    "resourceType": "Condition",
                    "id": f"{encounter_id}-sym",
                    "meta": {
                        "profile": ["http://hl7.org/fhir/StructureDefinition/Condition"]
                    },
                    "clinicalStatus": {
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                            "display": "Active"
                        }]
                    },
                    "category": [{
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                            "code": "problem-list-item",
                            "display": "Problem List Item"
                        }]
                    }],
                    "code": {"text": symptoms},
                    "subject": {"reference": f"Patient/{pat_id}"},
                    "encounter": {"reference": f"Encounter/{encounter_id}"},
                    "recordedDate": encounter_start
                })
                
            # Prescriptions MedicationRequest
            prescriptions = record.get("prescription", [])
            for idx, rx in enumerate(prescriptions):
                rx_id = f"{encounter_id}-rx-{idx}"
                med_name = rx.get("name")
                
                med_req = {
                    "resourceType": "MedicationRequest",
                    "id": rx_id,
                    "meta": {
                        "profile": ["http://hl7.org/fhir/StructureDefinition/MedicationRequest"]
                    },
                    "status": "completed",
                    "intent": "order",
                    "medicationCodeableConcept": {
                        "text": med_name
                    },
                    "subject": {"reference": f"Patient/{pat_id}"},
                    "encounter": {"reference": f"Encounter/{encounter_id}"},
                    "authoredOn": encounter_start,
                    "requester": {"reference": f"Practitioner/{doc_id}"} if doc_id else None,
                    "dosageInstruction": []
                }
                
                dose_text = rx.get("dose")
                if rx.get("note"):
                    dose_text = f"{dose_text} ({rx.get('note')})"
                if dose_text:
                    med_req["dosageInstruction"].append({
                        "sequence": 1,
                        "text": dose_text
                    })
                    
                quantity = rx.get("quantity")
                if quantity:
                    try:
                        med_req["dispenseRequest"] = {
                            "quantity": {
                                "value": float(quantity),
                                "unit": "tablets/units"
                            }
                        }
                    except ValueError:
                        pass
                        
                fhir_resources.append(med_req)
                
            # Vital Signs Observations
            vitals = record.get("vital_signs", {})
            
            # Pulse
            pulse = vitals.get("pulse")
            if pulse:
                try:
                    obs = make_standard_observation(
                        obs_id=f"{encounter_id}-v-pulse",
                        status="final",
                        category=[{
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "vital-signs",
                                "display": "Vital Signs"
                            }]
                        }],
                        code={
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "8867-4",
                                "display": "Heart rate"
                            }]
                        },
                        subject_ref={"reference": f"Patient/{pat_id}"},
                        encounter_ref={"reference": f"Encounter/{encounter_id}"},
                        effective_dt=encounter_start
                    )
                    obs["valueQuantity"] = {
                        "value": float(pulse),
                        "unit": "/min",
                        "system": "http://unitsofmeasure.org",
                        "code": "/min"
                    }
                    fhir_resources.append(obs)
                except ValueError:
                    pass
                    
            # Temperature
            temp = vitals.get("temperature")
            if temp:
                try:
                    obs = make_standard_observation(
                        obs_id=f"{encounter_id}-v-temp",
                        status="final",
                        category=[{
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "vital-signs",
                                "display": "Vital Signs"
                            }]
                        }],
                        code={
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "8310-5",
                                "display": "Body temperature"
                            }]
                        },
                        subject_ref={"reference": f"Patient/{pat_id}"},
                        encounter_ref={"reference": f"Encounter/{encounter_id}"},
                        effective_dt=encounter_start
                    )
                    obs["valueQuantity"] = {
                        "value": float(temp),
                        "unit": "C",
                        "system": "http://unitsofmeasure.org",
                        "code": "Cel"
                    }
                    fhir_resources.append(obs)
                except ValueError:
                    pass
                    
            # Weight
            wt = vitals.get("weight")
            if wt:
                try:
                    obs = make_standard_observation(
                        obs_id=f"{encounter_id}-v-weight",
                        status="final",
                        category=[{
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "vital-signs",
                                "display": "Vital Signs"
                            }]
                        }],
                        code={
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "29463-7",
                                "display": "Body weight"
                            }]
                        },
                        subject_ref={"reference": f"Patient/{pat_id}"},
                        encounter_ref={"reference": f"Encounter/{encounter_id}"},
                        effective_dt=encounter_start
                    )
                    obs["valueQuantity"] = {
                        "value": float(wt),
                        "unit": "kg",
                        "system": "http://unitsofmeasure.org",
                        "code": "kg"
                    }
                    fhir_resources.append(obs)
                except ValueError:
                    pass
                    
            # Blood Pressure
            bp_str = vitals.get("blood_pressure")
            if bp_str:
                parts = str(bp_str).split("/")
                systolic = None
                diastolic = None
                if len(parts) == 2:
                    try:
                        systolic = float(parts[0].strip())
                        diastolic = float(parts[1].strip())
                    except ValueError:
                        pass
                elif len(parts) == 1:
                    try:
                        systolic = float(parts[0].strip())
                    except ValueError:
                        pass
                        
                bp_obs = make_standard_observation(
                    obs_id=f"{encounter_id}-v-bp",
                    status="final",
                    category=[{
                        "coding": [{
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "vital-signs",
                            "display": "Vital Signs"
                        }]
                    }],
                    code={
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "85354-9",
                            "display": "Blood pressure systolic & diastolic"
                        }]
                    },
                    subject_ref={"reference": f"Patient/{pat_id}"},
                    encounter_ref={"reference": f"Encounter/{encounter_id}"},
                    effective_dt=encounter_start
                )
                
                bp_obs["component"] = []
                if systolic is not None:
                    bp_obs["component"].append({
                        "code": {
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "8480-6",
                                "display": "Systolic blood pressure"
                            }]
                        },
                        "valueQuantity": {
                            "value": systolic,
                            "unit": "mmHg",
                            "system": "http://unitsofmeasure.org",
                            "code": "mm[Hg]"
                        }
                    })
                if diastolic is not None:
                    bp_obs["component"].append({
                        "code": {
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "8462-4",
                                "display": "Diastolic blood pressure"
                            }]
                        },
                        "valueQuantity": {
                            "value": diastolic,
                            "unit": "mmHg",
                            "system": "http://unitsofmeasure.org",
                            "code": "mm[Hg]"
                        }
                    })
                    
                if bp_obs["component"]:
                    fhir_resources.append(bp_obs)

    # 7. Package in FHIR Bundle and format clean output
    bundle = {
        "resourceType": "Bundle",
        "id": f"bundle-export-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "type": "collection",
        "timestamp": datetime.now().isoformat() + "+07:00",
        "entry": []
    }
    
    # Recursively remove null and empty values from each resource
    # before adding them to the bundle to ensure validation compatibility.
    for resource in fhir_resources:
        cleaned_res = clean_empty_fields(resource)
        if cleaned_res:
            res_type = cleaned_res.get("resourceType")
            res_id = cleaned_res.get("id")
            
            bundle["entry"].append({
                "fullUrl": f"https://doctorportal.vn/fhir/{res_type}/{res_id}",
                "resource": cleaned_res
            })
            
    return bundle

def main():
    # Configure stdout to use UTF-8 to prevent encoding crashes on Windows console
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

    # Paths definition
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    parent_dir = os.path.dirname(project_dir)
    
    # Try different export file candidates
    export_candidates = [
        os.path.join(parent_dir, "nckh-f46fb-default-rtdb-export (6).json"),
        os.path.join(parent_dir, "nckh-f46fb-default-rtdb-export.json"),
        os.path.join(project_dir, "nckh-f46fb-default-rtdb-export.json"),
    ]
    
    source_file = None
    for candidate in export_candidates:
        if os.path.exists(candidate):
            source_file = candidate
            break
            
    if not source_file:
        print("[ERROR] Cannot find source JSON database export file!")
        sys.exit(1)
        
    print(f"[INFO] Reading database export from: {source_file}")
    with open(source_file, "r", encoding="utf-8") as f:
        db_data = json.load(f)
        
    print("[INFO] Converting database to HL7 FHIR Release 4 (R4)...")
    fhir_bundle = convert_to_fhir(db_data)
    
    output_file = os.path.join(script_dir, "fhir_export_output.json")
    print(f"[INFO] Saving FHIR Bundle to: {output_file}")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(fhir_bundle, f, indent=2, ensure_ascii=False)
        
    # Count resources mapped
    resource_counts = {}
    for entry in fhir_bundle.get("entry", []):
        res_type = entry.get("resource", {}).get("resourceType")
        resource_counts[res_type] = resource_counts.get(res_type, 0) + 1
        
    print("\n[SUCCESS] Successfully exported database to HL7 FHIR standard!")
    print(f"Total Resources Mapped: {len(fhir_bundle.get('entry', []))}")
    for res_type, count in sorted(resource_counts.items()):
        print(f"  - {res_type}: {count}")

if __name__ == "__main__":
    main()
