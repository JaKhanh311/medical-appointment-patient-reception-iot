"""
Firebase Realtime Database utilities - Using actual Firebase RTDB
"""
from services.firebase import (
    db,
    firebase_create_user_with_email_password,
    firebase_get_user_by_email,
    firebase_sign_in_with_email_password,
    firebase_user_exists,
    firebase_update_user_account,
)
from datetime import date as date_type, datetime, timedelta
import time
import unicodedata


_RTDB_DATE_INDEX_WARNING_SHOWN = False


def _doctor_key_variants(doctor_id):
    doctor_key = str(doctor_id or "").strip()
    if not doctor_key:
        return []

    variants = [doctor_key]
    if doctor_key.startswith("doc_"):
        variants.append(doctor_key[4:])
    else:
        variants.append(f"doc_{doctor_key}")

    # Keep order but dedupe.
    seen = set()
    ordered = []
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _normalize_appointment_day(value):
    text = str(value or "").strip()
    if not text:
        return ""

    if "T" in text:
        text = text.split("T", 1)[0]

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            continue

    return text


def _appointment_new_lookup_get(appointment_id):
    try:
        lookup = db.child("appointment_new_lookup").child(str(appointment_id or "").strip()).get() or {}
        return lookup if isinstance(lookup, dict) else {}
    except Exception:
        return {}


def _appointment_new_lookup_set(appointment_id, doctor_id, day):
    try:
        db.child("appointment_new_lookup").child(str(appointment_id or "").strip()).set({
            "doctorID": str(doctor_id or "").strip(),
            "date": str(day or "").strip(),
        })
    except Exception:
        pass


def _appointment_new_lookup_delete(appointment_id):
    try:
        db.child("appointment_new_lookup").child(str(appointment_id or "").strip()).delete()
    except Exception:
        pass


def _scan_appointment_new_by_id(appointment_id):
    """Fallback when lookup index is missing: scan appointment_new tree for one ID."""
    target_id = str(appointment_id or "").strip()
    if not target_id:
        return None, "", ""

    try:
        root = db.child("appointment_new").get() or {}
    except Exception:
        root = {}

    if not isinstance(root, dict):
        return None, "", ""

    for doctor_key, doctor_node in root.items():
        if not isinstance(doctor_node, dict):
            continue
        for day_key, day_node in doctor_node.items():
            if not isinstance(day_node, dict):
                continue
            apt = day_node.get(target_id)
            if isinstance(apt, dict):
                apt_copy = apt.copy()
                apt_copy["id"] = target_id
                _appointment_new_lookup_set(target_id, doctor_key, day_key)
                return apt_copy, str(doctor_key or ""), str(day_key or "")

    return None, "", ""


# =========================
# APPOINTMENTS
# =========================

# Snapshot cache for the full appointment_new tree. Used by admin views that
# apply many in-memory filters in sequence — without it every filter change
# would trigger a fresh ~MB read from Firebase RTDB.
_ALL_APTS_CACHE_TTL = 30  # seconds
_all_apts_cache: dict = {"snapshot": None, "ts": 0.0}

# Lightweight caches for doctors and specialties lists (rarely change).
_doctors_cache: dict = {"data": None, "ts": 0.0}
_specialties_cache: dict = {"data": None, "ts": 0.0}


def _all_apts_cache_get():
    snap = _all_apts_cache.get("snapshot")
    ts = _all_apts_cache.get("ts") or 0.0
    if snap is None:
        return None
    if (time.monotonic() - ts) > _ALL_APTS_CACHE_TTL:
        return None
    return snap


def _all_apts_cache_set(snapshot):
    _all_apts_cache["snapshot"] = list(snapshot) if isinstance(snapshot, list) else None
    _all_apts_cache["ts"] = time.monotonic()


def _invalidate_all_appointments_cache():
    _all_apts_cache["snapshot"] = None
    _all_apts_cache["ts"] = 0.0


# Registry of patient-record-search cache keys (one per doctor). The view
# inserts the key when it caches data; this helper clears them all when a new
# medical record is written so doctors immediately see fresh data.
_patient_record_search_keys: set = set()


def _register_patient_record_search_cache_key(key: str):
    if key:
        _patient_record_search_keys.add(key)


def _invalidate_patient_record_search_cache():
    try:
        from django.core.cache import cache as _django_cache
        keys_snapshot = list(_patient_record_search_keys)
        for k in keys_snapshot:
            try:
                _django_cache.delete(k)
            except Exception:
                pass
        _patient_record_search_keys.clear()
    except Exception:
        # Django not available or other unexpected error — do nothing.
        pass


def get_all_appointments():
    """Get all appointments from appointment_new/{doctor}/{date}/{appointmentId}.

    Optimisation: keep a short-lived (30 s) snapshot in process so that admin
    pages which apply multiple in-memory filters do not re-read the entire
    appointment tree on every request. The cache is invalidated by
    ``_invalidate_all_appointments_cache`` whenever an appointment is created
    or modified.
    """
    cached = _all_apts_cache_get()
    if cached is not None:
        return [apt.copy() for apt in cached]

    try:
        root = db.child("appointment_new").get()
        if not root or not isinstance(root, dict):
            _all_apts_cache_set([])
            return []

        result = []
        for doctor_key, doctor_node in root.items():
            if not isinstance(doctor_node, dict):
                continue

            for day_key, day_node in doctor_node.items():
                if not isinstance(day_node, dict):
                    continue

                for apt_id, apt_data in day_node.items():
                    if not isinstance(apt_data, dict):
                        continue

                    apt = apt_data.copy()
                    apt["id"] = apt_id
                    if not apt.get("date"):
                        apt["date"] = day_key
                    if not apt.get("appointmentDate"):
                        apt["appointmentDate"] = apt.get("date")
                    if not apt.get("doctorID"):
                        apt["doctorID"] = doctor_key
                    result.append(apt)

        _all_apts_cache_set(result)
        return [apt.copy() for apt in result]
    except Exception as e:
        print(f"⚠️ Firebase error in get_all_appointments: {e}")
        return []


def get_today_appointments(doctor_id=None):
    """Get appointments for today"""
    try:
        today = date_type.today().isoformat()
        all_appointments = get_all_appointments()

        apps = [a for a in all_appointments if a.get("date") == today]
        if doctor_id:
            apps = [a for a in apps if a.get("doctorID") == doctor_id]

        return apps
    except Exception as e:
        print(f"⚠️ Firebase error get_today_appointments: {e}")
        return []


def get_appointments_by_date(date_str):
    """Get appointments by specific date (YYYY-MM-DD) and attach patient_info"""
    try:
        all_appointments = get_all_appointments()
        apps = [a for a in all_appointments if a.get("date") == date_str]

        # attach patient
        for apt in apps:
            pid = apt.get("patientID", "")
            patient = get_patient_by_id(pid)
            if patient:
                apt["patient_info"] = patient

        return apps
    except Exception as e:
        print(f"⚠️ Firebase error get_appointments_by_date: {e}")
        return []


# ---------------------------------------------------------------------------
# Short-lived in-process cache (15 s) for appointment + patient lookups.
# Eliminates redundant Firebase reads when examine_view is opened right after
# dashboard poll (which already fetched the same data).
# ---------------------------------------------------------------------------
_APT_CACHE_TTL = 15  # seconds
_apt_cache: dict = {}   # {appointment_id: (mono_ts, data_copy)}
_patient_cache: dict = {}  # {patient_id: (mono_ts, data_copy)}


def _apt_cache_get(appointment_id):
    entry = _apt_cache.get(appointment_id)
    if entry and (time.monotonic() - entry[0]) < _APT_CACHE_TTL:
        return entry[1].copy() if isinstance(entry[1], dict) else entry[1]
    return None


def _apt_cache_set(appointment_id, data):
    _apt_cache[appointment_id] = (time.monotonic(), data.copy() if isinstance(data, dict) else data)


def _apt_cache_invalidate(appointment_id):
    _apt_cache.pop(appointment_id, None)


def _patient_cache_get(patient_id):
    entry = _patient_cache.get(patient_id)
    if entry and (time.monotonic() - entry[0]) < _APT_CACHE_TTL:
        return entry[1].copy() if isinstance(entry[1], dict) else entry[1]
    return None


def _patient_cache_set(patient_id, data):
    _patient_cache[patient_id] = (time.monotonic(), data.copy() if isinstance(data, dict) else data)


def get_appointment_by_id(appointment_id):
    """Get appointment from Firebase RTDB (with 15 s in-process cache)."""
    cached = _apt_cache_get(appointment_id)
    if cached is not None:
        return cached
    try:
        apt_id = str(appointment_id or "").strip()
        if not apt_id:
            return None

        lookup = _appointment_new_lookup_get(apt_id)
        doctor_id = str(lookup.get("doctorID") or "").strip()
        day_key = _normalize_appointment_day(lookup.get("date"))

        apt = None
        if doctor_id and day_key:
            try:
                apt = db.child("appointment_new").child(doctor_id).child(day_key).child(apt_id).get()
            except Exception:
                apt = None

        if not isinstance(apt, dict):
            apt, doctor_id, day_key = _scan_appointment_new_by_id(apt_id)
            if not isinstance(apt, dict):
                return None

        apt = apt.copy()
        apt["id"] = apt_id
        if not apt.get("date"):
            apt["date"] = day_key
        if not apt.get("appointmentDate"):
            apt["appointmentDate"] = apt.get("date")
        if not apt.get("doctorID"):
            apt["doctorID"] = doctor_id
        _appointment_new_lookup_set(apt_id, apt.get("doctorID", ""), apt.get("date", ""))
        _apt_cache_set(apt_id, apt)
        return apt
    except Exception as e:
        print(f"⚠️ Firebase error in get_appointment_by_id: {e}")
        return None


def update_appointment(appointment_id, **kwargs):
    """Update appointment"""
    _apt_cache_invalidate(appointment_id)  # evict stale cache on write
    _invalidate_all_appointments_cache()
    try:
        apt_id = str(appointment_id or "").strip()
        if not apt_id:
            return None

        current = get_appointment_by_id(apt_id)
        if not isinstance(current, dict):
            return None

        old_doctor = str(current.get("doctorID") or "").strip()
        old_day = _normalize_appointment_day(current.get("date") or current.get("appointmentDate"))

        merged = current.copy()
        merged.update(kwargs or {})

        new_doctor = str(merged.get("doctorID") or old_doctor).strip()
        new_day = _normalize_appointment_day(merged.get("date") or merged.get("appointmentDate") or old_day)
        if new_day:
            merged["date"] = new_day
            merged["appointmentDate"] = new_day

        # Move node if doctor/day changed.
        if old_doctor and old_day and (old_doctor != new_doctor or old_day != new_day):
            try:
                db.child("appointment_new").child(old_doctor).child(old_day).child(apt_id).delete()
            except Exception:
                pass

        db.child("appointment_new").child(new_doctor).child(new_day).child(apt_id).set(merged)
        _appointment_new_lookup_set(apt_id, new_doctor, new_day)
        return get_appointment_by_id(appointment_id)
    except Exception as e:
        print(f"⚠️ Firebase error update_appointment: {e}")
        return None


def mark_scheduled_appointments_no_show(date_str, session_key, doctor_id=None):
    """Close a session by marking leftover scheduled appointments as no_show.
    
    Optimized: queries only appointment_new/{doctor_id}/{date} instead of all appointments.
    """
    try:
        selected_date = str(date_str or "").strip()
        session_key = str(session_key or "").strip().lower()
        if not selected_date or session_key not in {"morning", "afternoon"}:
            return 0

        doctor_id = str(doctor_id or "").strip()
        if not doctor_id:
            return 0

        # Targeted query: only this doctor's appointments for this date
        doctor_keys = [doctor_id]
        if doctor_id.startswith("doc_"):
            doctor_keys.append(doctor_id[4:])
        else:
            doctor_keys.append(f"doc_{doctor_id}")

        updated_count = 0
        for dk in doctor_keys:
            try:
                day_node = db.child("appointment_new").child(dk).child(selected_date).get() or {}
            except Exception:
                continue

            if not isinstance(day_node, dict):
                continue

            for apt_id, apt_data in day_node.items():
                if not isinstance(apt_data, dict):
                    continue

                appointment_status = str(apt_data.get("status") or "").strip().lower()
                if appointment_status != "scheduled":
                    continue

                appointment_session = str(
                    apt_data.get("session")
                    or _normalize_session_from_time(apt_data.get("time", ""))
                    or ""
                ).strip().lower()

                if appointment_session != session_key:
                    continue

                update_appointment(
                    apt_id,
                    status="no_show",
                    noShowReason="session_closed",
                    noShowAt=datetime.now().isoformat(),
                )
                updated_count += 1

        return updated_count
    except Exception as e:
        print(f"⚠️ Firebase error mark_scheduled_appointments_no_show: {e}")
        return 0


# =========================
# PATIENTS
# =========================

def get_patient_by_id(patient_id):
    """Get patient details from Firebase RTDB (with 15 s in-process cache)."""
    cached = _patient_cache_get(patient_id)
    if cached is not None:
        return cached
    try:
        patient = db.child("patients").child(patient_id).get()
        if patient is None:
            return None
        if isinstance(patient, dict):
            patient = patient.copy()
        patient["id"] = patient_id
        _patient_cache_set(patient_id, patient)
        return patient
    except Exception as e:
        print(f"⚠️ Firebase error in get_patient_by_id: {e}")
        return None


def _normalize_patient_gender(gender_value):
    normalized = (gender_value or "").strip().lower()
    if normalized in {"nam", "male", "m"}:
        return "Male"
    if normalized in {"nu", "nữ", "female", "f"}:
        return "Female"
    return (gender_value or "").strip()


def _normalize_session_from_time(time_value):
    """Infer appointment session from HH:MM string."""
    try:
        hour = int(str(time_value).strip().split(":")[0])
    except Exception:
        return "other"

    if 7 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    return "other"


def create_walk_in_patient(patient_data: dict):
    """Create a patient record for direct walk-in booking flow."""
    try:
        patient_data = patient_data or {}
        now_ms = int(time.time() * 1000)

        patient_ref = db.child("patients").push({})
        patient_id = getattr(patient_ref, "key", None)
        if not patient_id:
            return None

        requested_user_id = (patient_data.get("user_id") or "").strip()

        payload = {
            "patientID": patient_id,
            "name": (patient_data.get("name") or "").strip(),
            "nickname": (patient_data.get("nickname") or "").strip(),
            "birthdate": (patient_data.get("birthdate") or "").strip(),
            "gender": _normalize_patient_gender(patient_data.get("gender")),
            "phone": (patient_data.get("phone") or "").strip(),
            "email": (patient_data.get("email") or "").strip(),
            "address": (patient_data.get("address") or "").strip(),
            "occupation": (patient_data.get("occupation") or "").strip(),
            "nationality": (patient_data.get("nationality") or "").strip(),
            "ethnicity": (patient_data.get("ethnicity") or "").strip(),
            "identityNumber": (patient_data.get("identity_number") or "").strip(),
            "avatarBase64": (patient_data.get("avatar_base64") or "").strip(),
            "role": (patient_data.get("role") or "self").strip() or "self",
            "priorityGroup": (patient_data.get("priority_group") or "").strip(),
            "profileVerified": False,
            "createdAt": now_ms,
            "updatedAt": now_ms,
            "userID": requested_user_id or patient_id,
            "medical_history": (patient_data.get("medical_history") or "").strip(),
        }

        db.child("patients").child(patient_id).set(payload)
        payload["id"] = patient_id
        return payload
    except Exception as e:
        print(f"⚠️ Firebase error create_walk_in_patient: {e}")
        return None


def create_walk_in_appointment(appointment_data: dict):
    """Create an appointment linked to a newly created or existing patient."""
    try:
        appointment_data = appointment_data or {}
        now_ms = int(time.time() * 1000)

        doctor_id = (appointment_data.get("doctor_id") or "").strip()
        date_value = _normalize_appointment_day((appointment_data.get("date") or "").strip())
        if not doctor_id or not date_value:
            return None

        appointment_ref = db.child("appointment_new").child(doctor_id).child(date_value).push({})
        appointment_id = getattr(appointment_ref, "key", None)
        if not appointment_id:
            return None

        time_value = (appointment_data.get("time") or "").strip()

        payload = {
            "appointmentID": appointment_id,
            "appointmentDate": date_value,
            "bookingType": (appointment_data.get("booking_type") or "doctor").strip() or "doctor",
            "createdAt": now_ms,
            "updatedAt": now_ms,
            "date": date_value,
            "time": time_value,
            "session": (appointment_data.get("session") or _normalize_session_from_time(time_value)).strip() or "other",
            "doctorID": (appointment_data.get("doctor_id") or "").strip(),
            "doctorName": (appointment_data.get("doctor_name") or "").strip(),
            "specialtyID": (appointment_data.get("specialty_id") or "").strip(),
            "specialtyName": (appointment_data.get("specialty_name") or "").strip(),
            "patientID": (appointment_data.get("patient_id") or "").strip(),
            "status": (appointment_data.get("status") or "scheduled").strip() or "scheduled",
            "reason": (appointment_data.get("reason") or "").strip(),
            "notes": (appointment_data.get("notes") or "").strip(),
            "location": (appointment_data.get("location") or "").strip(),
            "international": bool(appointment_data.get("international", False)),
            "userID": (appointment_data.get("user_id") or appointment_data.get("patient_id") or "").strip(),
        }

        db.child("appointment_new").child(doctor_id).child(date_value).child(appointment_id).set(payload)
        _appointment_new_lookup_set(appointment_id, doctor_id, date_value)

        payload["id"] = appointment_id
        _invalidate_all_appointments_cache()
        return payload
    except Exception as e:
        print(f"⚠️ Firebase error create_walk_in_appointment: {e}")
        return None


def create_referral_appointment(source_appointment_id, target_doctor_id, referral_data):
    """Create a new appointment as referral from another doctor.

    Args:
        source_appointment_id: The original appointment being referred from.
        target_doctor_id: The doctor receiving the referral.
        referral_data: Dict with keys: date, session, reason, priority_note,
                       source_doctor_id, source_doctor_name, patient_id,
                       target_doctor_name, target_specialty_id, target_specialty_name.

    Returns:
        The created appointment dict or None on failure.
    """
    try:
        referral_data = referral_data or {}
        now_ms = int(time.time() * 1000)

        target_doctor_id = str(target_doctor_id or "").strip()
        date_value = _normalize_appointment_day(str(referral_data.get("date") or "").strip())
        if not target_doctor_id or not date_value:
            return None

        # Create new appointment node under target doctor
        appointment_ref = db.child("appointment_new").child(target_doctor_id).child(date_value).push({})
        appointment_id = getattr(appointment_ref, "key", None)
        if not appointment_id:
            return None

        session_value = str(referral_data.get("session") or "morning").strip()

        referral_from = {
            "doctorID": str(referral_data.get("source_doctor_id") or "").strip(),
            "doctorName": str(referral_data.get("source_doctor_name") or "").strip(),
            "appointmentID": str(source_appointment_id or "").strip(),
            "reason": str(referral_data.get("reason") or "").strip(),
            "date": datetime.now().isoformat(),
        }

        payload = {
            "appointmentID": appointment_id,
            "appointmentDate": date_value,
            "bookingType": "referral",
            "createdAt": now_ms,
            "updatedAt": now_ms,
            "date": date_value,
            "time": "",
            "session": session_value,
            "doctorID": target_doctor_id,
            "doctorName": str(referral_data.get("target_doctor_name") or "").strip(),
            "specialtyID": str(referral_data.get("target_specialty_id") or "").strip(),
            "specialtyName": str(referral_data.get("target_specialty_name") or "").strip(),
            "patientID": str(referral_data.get("patient_id") or "").strip(),
            "status": "scheduled",
            "reason": str(referral_data.get("reason") or "").strip(),
            "notes": str(referral_data.get("priority_note") or "").strip(),
            "referralFrom": referral_from,
            "userID": str(referral_data.get("patient_id") or "").strip(),
        }

        db.child("appointment_new").child(target_doctor_id).child(date_value).child(appointment_id).set(payload)
        _appointment_new_lookup_set(appointment_id, target_doctor_id, date_value)

        # Update source appointment with referralTo metadata
        source_apt_id = str(source_appointment_id or "").strip()
        if source_apt_id:
            referral_to = {
                "targetDoctorID": target_doctor_id,
                "targetDoctorName": str(referral_data.get("target_doctor_name") or "").strip(),
                "targetSpecialtyName": str(referral_data.get("target_specialty_name") or "").strip(),
                "newAppointmentID": appointment_id,
                "date": date_value,
            }
            update_appointment(source_apt_id, referralTo=referral_to)

        payload["id"] = appointment_id
        return payload
    except Exception as e:
        print(f"⚠️ Firebase error create_referral_appointment: {e}")
        return None


def _clean_text(value):
    if value is None:
        return ""
    return " ".join(str(value).split())


def _truncate_text(value, max_length=180):
    text = _clean_text(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _coerce_timestamp(raw_value):
    try:
        return int(raw_value or 0)
    except Exception:
        return 0


def _format_article_date(raw_value):
    timestamp = _coerce_timestamp(raw_value)
    if timestamp <= 0:
        return ""

    try:
        if timestamp > 10**12:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y")
    except Exception:
        return ""


def _get_homepage_news_articles():
    articles_data = db.child("news_articles").get() or {}
    if not isinstance(articles_data, dict):
        return []

    articles = []
    for article_id, article_data in articles_data.items():
        if not isinstance(article_data, dict):
            continue
        if article_data.get("adminDeleted"):
            continue

        title = _clean_text(article_data.get("title"))
        summary = _clean_text(article_data.get("summary"))
        content = _clean_text(article_data.get("content"))
        if not title and not summary and not content:
            continue

        category_key = _clean_text(article_data.get("category")) or "general"
        category_label = _clean_text(article_data.get("categoryDisplayName")) or "Tin tức nổi bật"
        timestamp = _coerce_timestamp(article_data.get("updatedAt") or article_data.get("createdAt"))

        articles.append({
            "id": article_data.get("id") or article_id,
            "title": title or category_label,
            "summary": _truncate_text(summary or content, 220),
            "content_preview": _truncate_text(content, 320),
            "category": category_key,
            "category_display_name": category_label,
            "image_url": article_data.get("imageUrl") or article_data.get("thumbnailUrl") or "",
            "updated_label": _format_article_date(timestamp),
            "sort_timestamp": timestamp,
        })

    articles.sort(
        key=lambda item: (item.get("sort_timestamp", 0), item.get("title", "").lower()),
        reverse=True,
    )
    return articles


def get_homepage_news_articles(limit=6):
    """Build a flat list of the latest news articles for the public homepage."""
    try:
        articles = _get_homepage_news_articles()
        if limit:
            return articles[:limit]
        return articles
    except Exception as e:
        print(f"⚠️ Firebase error get_homepage_news_articles: {e}")
        return []


def get_homepage_news_sections(limit_per_category=3, max_sections=4):
    """Build grouped news sections for the public homepage from Firebase RTDB."""
    try:
        articles = _get_homepage_news_articles()

        grouped = {}
        for article in articles:
            category_key = article["category"]
            if category_key not in grouped:
                if max_sections and len(grouped) >= max_sections:
                    continue
                grouped[category_key] = {
                    "key": category_key,
                    "title": article["category_display_name"],
                    "articles": [],
                }

            if limit_per_category and len(grouped[category_key]["articles"]) >= limit_per_category:
                continue
            grouped[category_key]["articles"].append(article)

        return [section for section in grouped.values() if section["articles"]]
    except Exception as e:
        print(f"⚠️ Firebase error get_homepage_news_sections: {e}")
        return []


def get_patients_by_ids(patient_ids: list) -> dict:
    """
    Fetch multiple patients by ID using the per-patient cache (15 s TTL).
    Falls back to bulk read only when the cache is cold and there are many IDs.
    Returns dict {patientID: patient_data}.
    """
    try:
        if not patient_ids:
            return {}

        requested_ids = [str(pid).strip() for pid in patient_ids if str(pid).strip()]
        if not requested_ids:
            return {}

        result = {}
        uncached_ids = []

        # Serve from per-patient cache first (populated by get_patient_by_id).
        for pid in requested_ids:
            cached = _patient_cache_get(pid)
            if cached is not None:
                result[pid] = cached
            else:
                uncached_ids.append(pid)

        if not uncached_ids:
            return result

        # For a small number of misses, fetch individually (uses cache after first call).
        # For a large number, do a single bulk read and populate the cache.
        if len(uncached_ids) <= 10:
            for pid in uncached_ids:
                patient = get_patient_by_id(pid)  # also populates _patient_cache
                if patient:
                    result[pid] = patient
        else:
            patients_data = db.child("patients").get() or {}
            if isinstance(patients_data, dict):
                for pid in uncached_ids:
                    patient = patients_data.get(pid)
                    if isinstance(patient, dict):
                        patient = patient.copy()
                        patient["id"] = pid
                        _patient_cache_set(pid, patient)
                        result[pid] = patient

        return result
    except Exception as e:
        print(f"⚠️ Firebase error get_patients_by_ids: {e}")
        return {}


# =========================
# QUEUES
# =========================

def get_queue_by_key(queue_key: str) -> dict:
    """
    queue_key: "YYYY-MM-DD_session_spec_XXX"
    return dict tokens
    """
    try:
        queue_data = db.child("queues").child(queue_key).get()
        return queue_data or {}
    except Exception as e:
        print(f"⚠️ Firebase error get_queue_by_key: {e}")
        return {}


def find_token_by_appointment_id(queue_key: str, appointment_id: str):
    """
    Find token info by appointmentID inside queue_key.
    return (token_id, token_data) or (None, None)
    """
    q = get_queue_by_key(queue_key)
    if not isinstance(q, dict):
        return None, None

    for token_id, token_data in q.items():
        if isinstance(token_data, dict) and token_data.get("appointmentID") == appointment_id:
            return token_id, token_data
    return None, None


# =========================
# MEDICAL RECORDS
# =========================

def add_medical_record(doctor_id: str, patient_id: str, record_data: dict):
    """Create new medical record entry under medicalRecords/{patientID}/{entryID}.

    Cấu trúc:
        medicalRecords/
          └── {patientID}/
                └── entry_001, entry_002, ...

    Tổ chức theo patientID để truy vấn lịch sử khám nhanh (1 query).
    Mỗi entry chứa doctorID và specialtyID để kiểm tra quyền ở tầng ứng dụng.
    """
    try:
        patient_id = str(patient_id or "").strip()
        if not patient_id:
            print("⚠️ add_medical_record: thiếu patient_id")
            return None

        # Đếm số entry hiện tại
        current = db.child("medicalRecords").child(patient_id).get() or {}
        if not isinstance(current, dict):
            current = {}

        next_index = len(current) + 1
        entry_id = f"entry_{next_index:03d}"
        record_data = dict(record_data or {})
        record_data["recordID"] = entry_id
        record_data.setdefault("doctorID", str(doctor_id or "").strip())
        record_data.setdefault("patientID", patient_id)

        db.child("medicalRecords").child(patient_id).child(entry_id).set(record_data)
        # Invalidate patient-record-search cache so doctors see fresh records
        # the next time they open the search page.
        _invalidate_patient_record_search_cache()
        return entry_id
    except Exception as e:
        print(f"⚠️ Firebase error add_medical_record: {e}")
        return None



def doctor_can_access_appointment(doctor_id: str, appointment: dict, doctor_specialty: str = "", doctor_cache=None) -> bool:
    """Allow access when the doctor owns the appointment or shares its specialty."""
    try:
        doctor_id = str(doctor_id or "").strip()
        if not doctor_id or not isinstance(appointment, dict):
            return False

        apt_doctor_id = str(appointment.get("doctorID") or "").strip()
        if apt_doctor_id == doctor_id:
            return True

        normalized_specialty = str(doctor_specialty or "").strip().strip('"\'')
        if not normalized_specialty:
            return False

        appointment_specialty = str(appointment.get("specialtyID") or "").strip().strip('"\'')
        if appointment_specialty:
            return appointment_specialty == normalized_specialty

        if not apt_doctor_id:
            return False

        doctor_cache = doctor_cache if isinstance(doctor_cache, dict) else {}
        if apt_doctor_id not in doctor_cache:
            doctor_cache[apt_doctor_id] = get_doctor_by_id(apt_doctor_id) or {}

        fallback_specialty = str(doctor_cache[apt_doctor_id].get("specialtyID") or "").strip().strip('"\'')
        return bool(fallback_specialty and fallback_specialty == normalized_specialty)
    except Exception as e:
        print(f"⚠️ Firebase error doctor_can_access_appointment: {e}")
        return False


def doctor_has_related_appointment(doctor_id: str, patient_id: str) -> bool:
    """Check whether a doctor can access a patient's records.

    Tối ưu: chỉ quét appointments của bác sĩ đang đăng nhập (targeted query)
    thay vì load toàn bộ appointment_new tree.

    Trả về True nếu:
    - Bác sĩ đã/đang khám bệnh nhân này (có appointment chung)
    - HOẶC bệnh nhân có appointment với bác sĩ cùng chuyên khoa
    """
    try:
        doctor_id = str(doctor_id or "").strip()
        patient_id = str(patient_id or "").strip()
        if not doctor_id or not patient_id:
            return False

        # 1) Kiểm tra nhanh: bác sĩ này có appointment trực tiếp với bệnh nhân không?
        doctor_keys = _doctor_key_variants(doctor_id)
        for dk in doctor_keys:
            try:
                doctor_node = db.child("appointment_new").child(dk).get() or {}
            except Exception:
                continue
            if not isinstance(doctor_node, dict):
                continue
            for day_key, day_node in doctor_node.items():
                if not isinstance(day_node, dict):
                    continue
                for apt_id, apt_data in day_node.items():
                    if not isinstance(apt_data, dict):
                        continue
                    if str(apt_data.get("patientID") or "").strip() == patient_id:
                        return True

        # 2) Kiểm tra mở rộng: bệnh nhân có appointment với bác sĩ cùng chuyên khoa?
        doctor = get_doctor_by_id(doctor_id) or {}
        doctor_specialty = str(doctor.get("specialtyID") or "").strip().strip('"\'')
        if not doctor_specialty:
            return False

        # Lấy danh sách bác sĩ cùng chuyên khoa (từ cache nếu có)
        all_doctors = db.child("doctors").get() or {}
        if not isinstance(all_doctors, dict):
            return False

        same_specialty_keys = set()
        for doc_key, doc_data in all_doctors.items():
            if not isinstance(doc_data, dict):
                continue
            spec = str(doc_data.get("specialtyID") or "").strip().strip('"\'')
            if spec == doctor_specialty:
                same_specialty_keys.update(_doctor_key_variants(doc_key))

        # Quét appointments của các bác sĩ cùng chuyên khoa (đã loại bác sĩ hiện tại ở bước 1)
        for dk in same_specialty_keys:
            if dk in [str(v) for v in doctor_keys]:
                continue  # đã kiểm tra ở bước 1
            try:
                doctor_node = db.child("appointment_new").child(dk).get() or {}
            except Exception:
                continue
            if not isinstance(doctor_node, dict):
                continue
            for day_key, day_node in doctor_node.items():
                if not isinstance(day_node, dict):
                    continue
                for apt_id, apt_data in day_node.items():
                    if not isinstance(apt_data, dict):
                        continue
                    if str(apt_data.get("patientID") or "").strip() == patient_id:
                        return True

        return False
    except Exception as e:
        print(f"⚠️ Firebase error doctor_has_related_appointment: {e}")
        return False


def get_patient_medical_records_for_doctor(doctor_id: str, patient_id: str, trust_access: bool = False):
    """Return patient medical records mà bác sĩ có quyền xem.

    Cấu trúc: medicalRecords/{patientID}/{entryID}
    Mỗi entry chứa doctorID và specialtyID.

    Logic quyền truy cập (kiểm tra trực tiếp trên từng record):
    - entry.doctorID == doctor_id hiện tại → cho xem
    - entry.specialtyID == specialtyID của bác sĩ hiện tại → cho xem

    Không cần quét appointments, không cần hàm doctor_has_related_appointment().
    Rất nhanh: chỉ 1 query Firebase + filter ở Python.
    """
    try:
        patient_id = str(patient_id or "").strip()
        doctor_id = str(doctor_id or "").strip()
        if not patient_id or not doctor_id:
            return []

        # Lấy specialtyID của bác sĩ đang đăng nhập
        doctor = get_doctor_by_id(doctor_id) or {}
        doctor_specialty = str(doctor.get("specialtyID") or "").strip().strip('"\'')

        # 1 query duy nhất: đọc toàn bộ records của bệnh nhân
        records_data = db.child("medicalRecords").child(patient_id).get() or {}
        if not isinstance(records_data, dict):
            return []

        records = []
        for record_id, record in records_data.items():
            if not isinstance(record, dict):
                continue

            # Kiểm tra quyền trực tiếp trên record
            record_doctor_id = str(record.get("doctorID") or "").strip()
            record_specialty_id = str(record.get("specialtyID") or "").strip().strip('"\'')

            # Điều kiện 1: bác sĩ này đã khám (doctorID match)
            is_own_record = record_doctor_id == doctor_id

            # Điều kiện 2: cùng chuyên khoa (specialtyID match)
            is_same_specialty = (
                doctor_specialty
                and record_specialty_id
                and record_specialty_id == doctor_specialty
            )

            if not is_own_record and not is_same_specialty:
                continue  # Không có quyền xem record này

            item = record.copy()
            item["recordID"] = item.get("recordID") or record_id
            item["examDate"] = str(item.get("examDate") or "").strip()
            item["examTime"] = str(item.get("examTime") or "").strip()
            item["diagnosis"] = item.get("diagnosis") or ""
            item["symptoms"] = item.get("symptoms") or ""
            item["advice"] = item.get("advice") or ""
            records.append(item)

        records.sort(
            key=lambda x: (
                x.get("examDate", ""),
                x.get("examTime", ""),
                x.get("createdAt", 0),
            ),
            reverse=True,
        )
        return records
    except Exception as e:
        print(f"⚠️ Firebase error get_patient_medical_records_for_doctor: {e}")
        return []


# =========================
# EXAMINATION
# =========================

def get_appointment_with_patient_info(appointment_id):
    """Get appointment + attach patient_info"""
    try:
        apt = get_appointment_by_id(appointment_id)
        if not apt:
            return None
        pid = apt.get("patientID", "")
        patient = get_patient_by_id(pid)
        if patient:
            apt["patient_info"] = patient
        return apt
    except Exception as e:
        print(f"⚠️ Firebase error get_appointment_with_patient_info: {e}")
        return None


def save_examination(appointment_id, symptoms, diagnosis, advice, vital_signs=None, prescription=None):
    """
    Save examination record:
    - Update appointment status to "Đã khám"
    - Create medical record with all data
    - Store vital signs and prescription if provided
    """
    try:
        apt = get_appointment_by_id(appointment_id)
        if not apt:
            return None

        # Convert vital_signs dict to strings if None values exist
        if vital_signs is None:
            vital_signs = {}
        
        # Ensure all vital sign values are strings or empty
        vital_signs_clean = {
            "blood_pressure": str(vital_signs.get("blood_pressure", "")).strip() or "",
            "pulse": str(vital_signs.get("pulse", "")).strip() or "",
            "temperature": str(vital_signs.get("temperature", "")).strip() or "",
            "weight": str(vital_signs.get("weight", "")).strip() or "",
        }
        
        # Ensure prescription is a list
        if prescription is None:
            prescription = []
        
        # Update appointment: set status to "complete".
        update_appointment(
            appointment_id,
            symptoms=symptoms,
            diagnosis=diagnosis,
            advice=advice,
            status="complete",
            vital_signs=vital_signs_clean,
            prescription=prescription if prescription else [],
            last_examined_at=int(__import__("time").time())
        )

        # Keep queue token in sync with appointment completion.
        _mark_queue_token_completed(appointment_id)

        # Create medical record
        from django.utils import timezone as _tz
        _now_local = _tz.localtime()
        record = {
            "appointmentID": appointment_id,
            "patientID": apt.get("patientID", ""),
            "doctorID": apt.get("doctorID", ""),
            "specialtyID": apt.get("specialtyID", ""),
            "examDate": apt.get("date", ""),
            "examTime": _now_local.strftime("%H:%M"),
            
            # Clinical data
            "symptoms": symptoms,
            "diagnosis": diagnosis,
            "advice": advice,
            
            # Vital signs
            "vital_signs": vital_signs_clean,
            
            # Prescription
            "prescription": prescription if prescription else [],
            
            # Metadata
            "createdAt": int(__import__("time").time()),
            "status": "completed"
        }

        add_medical_record(apt.get("doctorID", ""), apt.get("patientID", ""), record)

        return get_appointment_by_id(appointment_id)

    except Exception as e:
        print(f"⚠️ Firebase error save_examination: {e}")
        return None


def _mark_queue_token_completed(appointment_id: str) -> bool:
    """Set queue token status=complete for the given appointment id."""
    try:
        target_id = str(appointment_id or "").strip()
        if not target_id:
            return False

        queues_root = db.child("queues").get() or {}
        if not isinstance(queues_root, dict):
            return False

        matched = False
        completed_at = int(time.time())

        # Canonical shape: queues/{doctor_id}/{date}/{token_id}
        for doctor_key, doctor_node in queues_root.items():
            if not isinstance(doctor_node, dict):
                continue

            for day_key, token_bucket in doctor_node.items():
                if not isinstance(token_bucket, dict):
                    continue

                for token_id, token_payload in token_bucket.items():
                    if not isinstance(token_payload, dict):
                        continue

                    token_appointment_id = str(
                        token_payload.get("appointmentId")
                        or token_payload.get("appointmentID")
                        or ""
                    ).strip()
                    if token_appointment_id != target_id:
                        continue

                    db.child("queues").child(str(doctor_key)).child(str(day_key)).child(str(token_id)).update({
                        "status": "complete",
                        "queueStatus": "complete",
                        "appointmentStatus": "complete",
                        "completedAt": completed_at,
                    })
                    matched = True

        return matched
    except Exception as e:
        print(f"⚠️ Firebase error _mark_queue_token_completed: {e}")
        return False


# =========================
# STATISTICS
# =========================

def get_appointments_by_time_slots():
    """Count today's appointments by hour range"""
    try:
        today = date_type.today().isoformat()
        all_appointments = get_all_appointments()
        today_appointments = [apt for apt in all_appointments if apt.get("date") == today]

        time_slots = {
            "7:00-8:00": 0,
            "8:00-9:00": 0,
            "9:00-10:00": 0,
            "10:00-11:00": 0,
            "11:00-12:00": 0,
            "12:00-13:00": 0,
            "13:00-14:00": 0,
            "14:00-15:00": 0,
            "15:00-16:00": 0,
            "16:00-17:00": 0
        }

        for apt in today_appointments:
            t = apt.get("time", "")
            if not t:
                continue
            try:
                hour = int(t.split(":")[0])
                for slot_range in time_slots.keys():
                    start_hour = int(slot_range.split(":")[0])
                    end_hour = int(slot_range.split("-")[1].split(":")[0])
                    if start_hour <= hour < end_hour:
                        time_slots[slot_range] += 1
                        break
            except:
                pass

        return [{"time": slot, "count": count} for slot, count in time_slots.items()]
    except Exception as e:
        print(f"⚠️ Firebase error get_appointments_by_time_slots: {e}")
        return []


# =========================
# AUTHENTICATION & AUTHORIZATION
# =========================

def authenticate_doctor(login_identifier, password):
    """Authenticate doctor by username or email.

    Returns:
        tuple[dict|None, str]: (doctor, message)
        - doctor is not None when authentication succeeds.
        - message contains a friendly failure reason when login fails after matching a doctor.
    """
    try:
        login_identifier = (login_identifier or "").strip()
        password = (password or "").strip()
        if not login_identifier or not password:
            return None, "Vui lòng nhập đầy đủ thông tin đăng nhập."

        identifier_lower = login_identifier.lower()

        doctors_data = db.child("doctors").get() or {}
        if not isinstance(doctors_data, dict):
            return None, "Không thể đọc dữ liệu tài khoản bác sĩ."

        matched_doctor = False
        last_doctor_error = ""

        for doc_id, doc_data in doctors_data.items():
            if not isinstance(doc_data, dict):
                continue
            doctor_username = str(doc_data.get("username", "")).strip().lower()
            doctor_email = str(doc_data.get("email", "")).strip().lower()
            if identifier_lower not in {doctor_username, doctor_email}:
                continue

            matched_doctor = True

            doctor = doc_data.copy()
            doctor["id"] = doc_id

            email = str(doctor.get("email", "")).strip()
            if email:
                try:
                    auth_data = firebase_sign_in_with_email_password(email=email, password=password)
                    auth_uid = str((auth_data or {}).get("localId", "")).strip()
                    if auth_uid and not str(doctor.get("userID", "")).strip():
                        db.child("doctors").child(doc_id).update({"userID": auth_uid})
                        doctor["userID"] = auth_uid
                    return doctor, ""
                except ValueError as exc:
                    last_doctor_error = str(exc).strip()

            if doc_data.get("password") == password:
                return doctor, ""

        if matched_doctor:
            if last_doctor_error:
                return None, last_doctor_error
            return None, "Mật khẩu không đúng hoặc tài khoản bác sĩ chưa được liên kết Firebase Authentication."

        return None, ""
    except Exception as e:
        print(f"⚠️ Firebase error authenticate_doctor: {e}")
        return None, "Không thể xác thực tài khoản bác sĩ lúc này."


def authenticate_admin_firebase(email, password):
    """Authenticate admin via Firebase Auth and verify admin role in RTDB users/{uid}."""
    try:
        email = (email or "").strip()
        password = (password or "").strip()

        if not email or not password:
            return False, "Vui lòng nhập đầy đủ email và mật khẩu.", None

        auth_data = firebase_sign_in_with_email_password(email=email, password=password)
        uid = (auth_data or {}).get("localId", "").strip()
        if not uid:
            return False, "Không lấy được UID từ Firebase Authentication.", None

        user_profile = db.child("users").child(uid).get() or {}
        profile_key = uid

        if not isinstance(user_profile, dict) or not user_profile:
            # Fallback for datasets where users node is keyed by random ID, not Firebase Auth UID.
            users_data = db.child("users").get() or {}
            target_email = email.lower()
            user_profile = {}
            profile_key = ""
            if isinstance(users_data, dict):
                for key, value in users_data.items():
                    if not isinstance(value, dict):
                        continue
                    value_email = str(value.get("email", "")).strip().lower()
                    if value_email == target_email:
                        user_profile = value
                        profile_key = key
                        break

        if not isinstance(user_profile, dict) or not user_profile:
            return False, "Không tìm thấy hồ sơ người dùng trong users của RTDB.", None

        role = str(user_profile.get("role", "")).strip().lower()
        if role != "admin":
            return False, "Tài khoản không có quyền admin trong dữ liệu users.", None

        if user_profile.get("active") is False:
            return False, "Tài khoản admin đang bị khóa (active = false).", None

        user_info = {
            "uid": uid,
            "profile_key": profile_key,
            "email": auth_data.get("email") or email,
            "name": user_profile.get("name") or "",
            "role": user_profile.get("role") or "",
            "id_token": auth_data.get("idToken") or "",
        }
        return True, "Đăng nhập quản trị thành công.", user_info
    except ValueError as e:
        return False, str(e), None
    except Exception as e:
        print(f"⚠️ Firebase error authenticate_admin_firebase: {e}")
        return False, "Không thể đăng nhập quản trị bằng Firebase.", None


def get_all_doctors():
    """Get all doctor accounts from Firebase RTDB (cached 30 s)."""
    cached = _doctors_cache.get("data")
    if cached is not None and (time.monotonic() - _doctors_cache.get("ts", 0)) < 30:
        return [d.copy() for d in cached]
    try:
        doctors_data = db.child("doctors").get() or {}
        if not isinstance(doctors_data, dict):
            return []

        doctors = []
        for doctor_id, doctor_data in doctors_data.items():
            if not isinstance(doctor_data, dict):
                continue
            item = doctor_data.copy()
            item["id"] = doctor_id
            doctors.append(item)

        doctors.sort(key=lambda x: (x.get("name") or "").lower())
        _doctors_cache["data"] = doctors
        _doctors_cache["ts"] = time.monotonic()
        return [d.copy() for d in doctors]
    except Exception as e:
        print(f"⚠️ Firebase error get_all_doctors: {e}")
        return []


def _get_user_profiles():
    """Get all user profiles from Firebase RTDB users node."""
    try:
        users_data = db.child("users").get() or {}
        if not isinstance(users_data, dict):
            return []

        profiles = []
        for profile_key, profile_data in users_data.items():
            if not isinstance(profile_data, dict):
                continue
            profile = profile_data.copy()
            profile["id"] = profile_key
            profiles.append(profile)
        return profiles
    except Exception as e:
        print(f"⚠️ Firebase error _get_user_profiles: {e}")
        return []


def _doctor_has_linked_auth_account(doctor, user_profiles=None):
    """Check whether a doctor already has a Firebase-auth-backed account."""
    doctor = doctor or {}
    doctor_id = str(doctor.get("id", "")).strip()
    doctor_uid = str(doctor.get("userID", "")).strip()
    doctor_email = str(doctor.get("email", "")).strip().lower()
    profiles = user_profiles if user_profiles is not None else _get_user_profiles()

    candidate_uids = set()
    if doctor_uid:
        candidate_uids.add(doctor_uid)

    for profile in profiles:
        profile_id = str(profile.get("id", "")).strip()
        profile_uid = str(profile.get("uid", "")).strip()
        if doctor_uid and (doctor_uid == profile_id or doctor_uid == profile_uid):
            if profile_id:
                candidate_uids.add(profile_id)
            if profile_uid:
                candidate_uids.add(profile_uid)

        if str(profile.get("role", "")).strip().lower() != "doctor":
            continue

        profile_doctor_id = str(profile.get("doctorID", "")).strip()
        profile_email = str(profile.get("email", "")).strip().lower()
        if (doctor_id and profile_doctor_id == doctor_id) or (doctor_email and profile_email == doctor_email):
            if profile_id:
                candidate_uids.add(profile_id)
            if profile_uid:
                candidate_uids.add(profile_uid)

    for uid in candidate_uids:
        if not uid:
            continue
        try:
            if firebase_user_exists(uid=uid):
                return True
        except ValueError as e:
            print(f"⚠️ Firebase warning _doctor_has_linked_auth_account(uid): {e}")

    if doctor_email:
        try:
            if firebase_user_exists(email=doctor_email):
                return True
        except ValueError as e:
            print(f"⚠️ Firebase warning _doctor_has_linked_auth_account(email): {e}")

    return False


def get_all_specialties():
    """Get all specialties from Firebase RTDB (cached 60 s — rarely changes)."""
    cached = _specialties_cache.get("data")
    if cached is not None and (time.monotonic() - _specialties_cache.get("ts", 0)) < 60:
        return [s.copy() for s in cached]
    try:
        specialties_data = db.child("specialties").get() or {}
        if not isinstance(specialties_data, dict):
            return []

        specialties = []
        for specialty_id, specialty_data in specialties_data.items():
            if not isinstance(specialty_data, dict):
                continue
            item = specialty_data.copy()
            item["id"] = specialty_id
            specialties.append(item)

        specialties.sort(key=lambda x: (x.get("name") or "").lower())
        _specialties_cache["data"] = specialties
        _specialties_cache["ts"] = time.monotonic()
        return [s.copy() for s in specialties]
    except Exception as e:
        print(f"⚠️ Firebase error get_all_specialties: {e}")
        return []


def get_all_hospitals():
    """Get all hospitals from Firebase RTDB"""
    try:
        hospitals_data = db.child("hospitals").get() or {}
        if not isinstance(hospitals_data, dict):
            return []

        hospitals = []
        for hospital_id, hospital_data in hospitals_data.items():
            if not isinstance(hospital_data, dict):
                continue
            item = hospital_data.copy()
            item["id"] = hospital_id
            hospitals.append(item)

        hospitals.sort(key=lambda x: (x.get("name") or x.get("fullName") or "").lower())
        return hospitals
    except Exception as e:
        print(f"⚠️ Firebase error get_all_hospitals: {e}")
        return []


def get_doctors_without_account():
    """Return doctors that do not have a complete Firebase-backed login yet."""
    doctors = get_all_doctors()
    user_profiles = _get_user_profiles()
    result = []
    for doctor in doctors:
        username = str(doctor.get("username", "")).strip()
        if not username or not _doctor_has_linked_auth_account(doctor, user_profiles):
            result.append(doctor)
    return result


def provision_existing_doctor_account(doctor_id, username, password, email=None):
    """Create Firebase Auth account and bind it to an existing doctor profile."""
    try:
        doctor_id = (doctor_id or "").strip()
        username = (username or "").strip()
        password = (password or "").strip()
        email = (email or "").strip()

        if not doctor_id:
            return False, "Thiếu mã bác sĩ.", None

        if not username or not password:
            return False, "Vui lòng nhập username và mật khẩu để cấp tài khoản.", None

        if len(password) < 6:
            return False, "Mật khẩu phải có ít nhất 6 ký tự.", None

        doctor = get_doctor_by_id(doctor_id)
        if not doctor:
            return False, "Không tìm thấy hồ sơ bác sĩ.", None

        if _doctor_has_linked_auth_account(doctor):
            return False, "Bác sĩ này đã có tài khoản Firebase Authentication.", doctor

        if not email:
            email = str(doctor.get("email", "")).strip()

        if not email:
            return False, "Bác sĩ chưa có email để tạo Firebase Authentication.", None

        existing_doctors = get_all_doctors()
        username_lower = username.lower()
        for item in existing_doctors:
            item_id = str(item.get("id", "")).strip()
            if item_id == doctor_id:
                continue
            if str(item.get("username", "")).strip().lower() == username_lower:
                return False, "Username đã tồn tại ở bác sĩ khác.", None

        uid = ""
        try:
            auth_created = firebase_create_user_with_email_password(
                email=email,
                password=password,
                display_name=doctor.get("name") or "",
            )
            uid = str((auth_created or {}).get("localId", "")).strip()
        except ValueError as exc:
            message = str(exc)
            if "Email đã tồn tại" not in message:
                raise

            # Email already exists in Firebase Auth: link to that account instead of failing.
            existing_user = firebase_get_user_by_email(email)
            uid = str(getattr(existing_user, "uid", "")).strip()
            if uid:
                firebase_update_user_account(
                    uid=uid,
                    password=password,
                    display_name=doctor.get("name") or "",
                )

        if not uid:
            return False, "Tạo tài khoản Firebase Authentication thất bại (không có UID).", None

        db.child("doctors").child(doctor_id).update({
            "username": username,
            "email": email,
            "userID": uid,
        })

        try:
            db.child("doctors").child(doctor_id).child("password").delete()
        except Exception:
            pass

        db.child("users").child(uid).update({
            "name": doctor.get("name") or "",
            "email": email,
            "role": "doctor",
            "active": True,
            "doctorID": doctor_id,
            "username": username,
        })

        updated = get_doctor_by_id(doctor_id)
        return True, "Cấp tài khoản bác sĩ thành công và đã lưu Firebase Authentication.", updated
    except ValueError as e:
        return False, str(e), None
    except Exception as e:
        print(f"⚠️ Firebase error provision_existing_doctor_account: {e}")
        return False, "Có lỗi khi cấp tài khoản cho bác sĩ.", None


def create_doctor_account(name, username, password, specialty_id="", doctor_data=None):
    """Create a new doctor profile in Firebase RTDB with account fields."""
    try:
        name = (name or "").strip()
        username = (username or "").strip()
        password = (password or "").strip()
        specialty_id = (specialty_id or "").strip()
        doctor_data = doctor_data or {}

        if not name or not username or not password:
            return False, "Vui lòng nhập đầy đủ họ tên, tên đăng nhập và mật khẩu.", None

        existing_doctors = get_all_doctors()
        username_lower = username.lower()

        if any((d.get("username") or "").lower() == username_lower for d in existing_doctors):
            return False, "Tên đăng nhập đã tồn tại.", None

        max_seq = 0
        for doc in existing_doctors:
            doctor_id = str(doc.get("id", ""))
            digits = "".join(ch for ch in doctor_id if ch.isdigit())
            if digits:
                max_seq = max(max_seq, int(digits))

        next_seq = max_seq + 1
        doctor_id = f"doc_{next_seq:03d}"

        specialty_map = {specialty_id: True} if specialty_id else {}

        payload = {
            "avatarUrl": doctor_data.get("avatarUrl", ""),
            "awards": doctor_data.get("awards", []),
            "biography": doctor_data.get("biography", ""),
            "certifications": doctor_data.get("certifications", ""),
            "dateOfBirth": doctor_data.get("dateOfBirth", ""),
            "doctorID": doctor_id,
            "education": doctor_data.get("education", ""),
            "email": doctor_data.get("email", ""),
            "expectedFee": doctor_data.get("expectedFee", 0),
            "experience": doctor_data.get("experience", 0),
            "gender": doctor_data.get("gender", ""),
            "hospitalID": doctor_data.get("hospitalID", ""),
            "isActive": doctor_data.get("isActive", True),
            "major": doctor_data.get("major", ""),
            "name": name,
            "phone": doctor_data.get("phone", ""),
            "positions": doctor_data.get("positions", []),
            "publications": doctor_data.get("publications", []),
            "rating": doctor_data.get("rating", 0),
            "services": doctor_data.get("services", []),
            "specialties": specialty_map,
            "specialtyID": specialty_id,
            "techniques": doctor_data.get("techniques", []),
            "title": doctor_data.get("title", ""),
            "userID": doctor_data.get("userID", f"uid_{doctor_id}"),
            "workplaces": doctor_data.get("workplaces", []),
            "username": username,
            "password": password,
        }

        db.child("doctors").child(doctor_id).set(payload)

        created = payload.copy()
        created["id"] = doctor_id
        _doctors_cache["data"] = None  # invalidate doctors list cache
        return True, "Thêm bác sĩ thành công.", created
    except Exception as e:
        print(f"⚠️ Firebase error create_doctor_account: {e}")
        return False, "Có lỗi khi thêm bác sĩ.", None


def update_doctor_account(doctor_id, name, username, specialty_id="", password=None, doctor_data=None):
    """Update doctor profile and sync linked Firebase account metadata when present."""
    try:
        doctor_id = (doctor_id or "").strip()
        name = (name or "").strip()
        username = (username or "").strip()
        specialty_id = (specialty_id or "").strip()
        password = (password or "").strip() if password is not None else ""
        doctor_data = doctor_data or {}

        if not doctor_id:
            return False, "Thiếu mã bác sĩ cần cập nhật.", None

        if not name or not username:
            return False, "Vui lòng nhập đầy đủ họ tên và tên đăng nhập.", None

        current = get_doctor_by_id(doctor_id)
        if not current:
            return False, "Không tìm thấy tài khoản bác sĩ.", None

        auth_uid = str(doctor_data.get("userID", current.get("userID", ""))).strip()

        # Username is managed as read-only in edit page.
        update_payload = {
            "avatarUrl": doctor_data.get("avatarUrl", current.get("avatarUrl", "")),
            "awards": doctor_data.get("awards", current.get("awards", [])),
            "biography": doctor_data.get("biography", current.get("biography", "")),
            "certifications": doctor_data.get("certifications", current.get("certifications", "")),
            "dateOfBirth": doctor_data.get("dateOfBirth", current.get("dateOfBirth", "")),
            "doctorID": doctor_id,
            "education": doctor_data.get("education", current.get("education", "")),
            "email": doctor_data.get("email", current.get("email", "")),
            "expectedFee": doctor_data.get("expectedFee", current.get("expectedFee", 0)),
            "experience": doctor_data.get("experience", current.get("experience", 0)),
            "gender": doctor_data.get("gender", current.get("gender", "")),
            "hospitalID": doctor_data.get("hospitalID", current.get("hospitalID", "")),
            "isActive": doctor_data.get("isActive", current.get("isActive", True)),
            "major": doctor_data.get("major", current.get("major", "")),
            "name": name,
            "phone": doctor_data.get("phone", current.get("phone", "")),
            "positions": doctor_data.get("positions", current.get("positions", [])),
            "publications": doctor_data.get("publications", current.get("publications", [])),
            "rating": doctor_data.get("rating", current.get("rating", 0)),
            "services": doctor_data.get("services", current.get("services", [])),
            "specialties": ({specialty_id: True} if specialty_id else current.get("specialties", {})),
            "specialtyID": specialty_id,
            "techniques": doctor_data.get("techniques", current.get("techniques", [])),
            "title": doctor_data.get("title", current.get("title", "")),
            "userID": doctor_data.get("userID", current.get("userID", f"uid_{doctor_id}")),
            "workplaces": doctor_data.get("workplaces", current.get("workplaces", [])),
            "username": username,
        }

        if auth_uid and not update_payload["email"]:
            return False, "Bác sĩ đã liên kết Firebase Authentication nên email không được để trống.", None

        if auth_uid:
            firebase_update_user_account(
                uid=auth_uid,
                email=update_payload["email"],
                password=password or None,
                display_name=name,
            )
        elif password:
            update_payload["password"] = password

        db.child("doctors").child(doctor_id).update(update_payload)

        if auth_uid:
            try:
                db.child("doctors").child(doctor_id).child("password").delete()
            except Exception:
                pass

            db.child("users").child(auth_uid).update({
                "name": name,
                "email": update_payload["email"],
                "role": "doctor",
                "active": True,
                "doctorID": doctor_id,
                "username": username,
            })

        updated = get_doctor_by_id(doctor_id) or {}
        _doctors_cache["data"] = None  # invalidate doctors list cache
        return True, "Cập nhật thông tin bác sĩ thành công.", updated
    except Exception as e:
        print(f"⚠️ Firebase error update_doctor_account: {e}")
        return False, "Có lỗi khi cập nhật bác sĩ.", None


def _normalize_text_no_accents(text):
    normalized = unicodedata.normalize("NFKD", (text or "").strip().lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.replace("đ", "d")


def build_doctor_patient_exam_history(doctor_id=None, date_from=None, date_to=None):
    """Build list of completed examinations, grouped-friendly for admin dashboard.

    Optimisation: when ``doctor_id`` is provided, read the single node
    ``appointment_new/{doctor_id}`` (all dates for that doctor) in ONE Firebase
    call, then filter by date range in Python. This is much faster than
    per-day reads (~1 call vs ~365 calls) while still being cheaper than
    reading the entire appointment_new tree (only 1 doctor's data).
    """
    try:
        norm_doctor_id = (doctor_id or "").strip() or None
        norm_from = (date_from or "").strip() or None
        norm_to = (date_to or "").strip() or None

        all_appointments = []
        if norm_doctor_id:
            # Single read of the doctor's entire date tree.
            doctor_variants = _doctor_key_variants(norm_doctor_id)
            seen_ids = set()
            for doctor_key in doctor_variants:
                doctor_node = db.child("appointment_new").child(doctor_key).get() or {}
                if not isinstance(doctor_node, dict):
                    continue
                for day_key, day_node in doctor_node.items():
                    if not isinstance(day_node, dict):
                        continue
                    # Quick date-range filter at the key level (YYYY-MM-DD keys).
                    if norm_from and day_key < norm_from:
                        continue
                    if norm_to and day_key > norm_to:
                        continue
                    for apt_id, apt_data in day_node.items():
                        if not apt_id or apt_id in seen_ids or not isinstance(apt_data, dict):
                            continue
                        seen_ids.add(apt_id)
                        apt = apt_data.copy()
                        apt["id"] = apt_id
                        if not apt.get("date"):
                            apt["date"] = day_key
                        if not apt.get("doctorID"):
                            apt["doctorID"] = doctor_key
                        all_appointments.append(apt)
        else:
            # No doctor filter → use the cached full-tree snapshot.
            all_appointments = get_all_appointments()

        rows = []
        doctor_ids = set()
        patient_ids = set()

        for apt in all_appointments:
            status = _normalize_text_no_accents(str(apt.get("status", "")))
            if status not in {"da kham", "completed", "complete"}:
                continue

            apt_doctor_id = (apt.get("doctorID") or "").strip()
            apt_patient_id = (apt.get("patientID") or "").strip()
            apt_date = (apt.get("date") or "").strip()

            if not apt_doctor_id or not apt_patient_id:
                continue

            if norm_doctor_id and apt_doctor_id != norm_doctor_id:
                continue

            if norm_from and apt_date and apt_date < norm_from:
                continue

            if norm_to and apt_date and apt_date > norm_to:
                continue

            doctor_ids.add(apt_doctor_id)
            patient_ids.add(apt_patient_id)

            rows.append({
                "appointment_id": apt.get("id") or apt.get("appointmentID") or "",
                "doctor_id": apt_doctor_id,
                "patient_id": apt_patient_id,
                "date": apt_date,
                "time": (apt.get("time") or "").strip(),
                "status": apt.get("status") or "Đã khám",
                "symptoms": apt.get("symptoms") or "",
                "diagnosis": apt.get("diagnosis") or "",
            })

        doctors_map = {}
        for did in doctor_ids:
            doctor = get_doctor_by_id(did) or {}
            doctors_map[did] = doctor

        patients_map = get_patients_by_ids(list(patient_ids))

        for row in rows:
            doctor = doctors_map.get(row["doctor_id"], {})
            patient = patients_map.get(row["patient_id"], {})

            row["doctor_name"] = doctor.get("name") or row["doctor_id"]
            row["doctor_username"] = doctor.get("username") or ""
            row["patient_name"] = patient.get("name") or row["patient_id"]
            row["patient_phone"] = patient.get("phone") or ""

        rows.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)
        return rows
    except Exception as e:
        print(f"⚠️ Firebase error build_doctor_patient_exam_history: {e}")
        return []


def get_doctor_by_id(doctor_id):
    """Get doctor details by ID"""
    try:
        doctor = db.child("doctors").child(doctor_id).get()
        if doctor is None:
            return None
        if isinstance(doctor, dict):
            doctor = doctor.copy()
        doctor["id"] = doctor_id
        return doctor
    except Exception as e:
        print(f"⚠️ Firebase error get_doctor_by_id: {e}")
        return None


def get_specialty_by_id(specialty_id):
    """Get specialty details by ID"""
    try:
        specialty = db.child("specialties").child(specialty_id).get()
        if specialty is None:
            return None
        if isinstance(specialty, dict):
            specialty = specialty.copy()
        specialty["id"] = specialty_id
        return specialty
    except Exception as e:
        print(f"⚠️ Firebase error get_specialty_by_id: {e}")
        return None


# =========================
# AUTHORIZED DATA ACCESS
# =========================

def get_today_appointments_for_doctor(doctor_id=None):
    """Get today's appointments filtered by doctor's specialty"""
    try:
        today = date_type.today().isoformat()
        all_appointments = get_all_appointments()
        today_appointments = [a for a in all_appointments if a.get("date") == today]

        if doctor_id:
            # determine specialty of logged-in doctor
            doctor = get_doctor_by_id(doctor_id)
            doctor_specialty = doctor.get("specialtyID").strip() if doctor and doctor.get("specialtyID") else None
            if doctor_specialty:
                # build cache of doctors to avoid repeated DB calls
                doctor_cache = {}
                def appointment_specialty(apt):
                    spec = apt.get("specialtyID")
                    if spec:
                        if isinstance(spec, str):
                            return spec.strip().strip('"\'')
                        return spec
                    # fallback: look up the appointment's doctor
                    did = apt.get("doctorID")
                    if not did:
                        return None
                    if did in doctor_cache:
                        cached = doctor_cache[did].get("specialtyID")
                        return cached.strip() if isinstance(cached, str) else cached
                    d = get_doctor_by_id(did)
                    doctor_cache[did] = d or {}
                    cached = doctor_cache[did].get("specialtyID")
                    return cached.strip() if isinstance(cached, str) else cached

                today_appointments = [
                    a for a in today_appointments
                    if appointment_specialty(a) == doctor_specialty or a.get("doctorID") == doctor_id
                ]

        return today_appointments
    except Exception as e:
        print(f"⚠️ Firebase error get_today_appointments_for_doctor: {e}")
        return []


def get_appointments_by_date_for_doctor(date_str, doctor_id=None):
    """Get appointments by date filtered by doctor's specialty"""
    try:
        return get_appointments_by_date_range_for_doctor(date_str, date_str, doctor_id)
    except Exception as e:
        print(f"[WARN] Firebase error get_appointments_by_date_for_doctor: {e}")
        return []


def _iter_iso_dates(start_date: str, end_date: str):
    """Yield YYYY-MM-DD values from start_date to end_date (inclusive)."""
    try:
        current = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        return

    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def _normalize_date_string(value):
    """Normalize common date payloads to YYYY-MM-DD when possible."""
    raw = str(value or "").strip()
    if not raw:
        return ""

    if "T" in raw:
        raw = raw.split("T", 1)[0]

    # ISO format first.
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except Exception:
        pass

    # Legacy/mobile payloads may store dd/mm/YYYY.
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
    except Exception:
        pass

    # Keep original if format is unknown.
    return raw


def _normalize_appointment_dates(apt):
    """Normalize date fields in-place and return normalized primary date value."""
    if not isinstance(apt, dict):
        return ""

    if not apt.get("date") and apt.get("appointmentDate"):
        apt["date"] = apt.get("appointmentDate")

    norm_date = _normalize_date_string(apt.get("date"))
    norm_appointment_date = _normalize_date_string(apt.get("appointmentDate"))

    if not norm_date and norm_appointment_date:
        norm_date = norm_appointment_date

    if norm_date:
        apt["date"] = norm_date
    if norm_appointment_date:
        apt["appointmentDate"] = norm_appointment_date

    return norm_date


def _fetch_appointments_by_date_range_secondary_index(start_date: str, end_date: str) -> list:
    """Compatibility wrapper: range fetch now scans appointment_new tree."""
    result = []
    all_apts = get_all_appointments()
    for apt in all_apts:
        if not isinstance(apt, dict):
            continue
        apt_copy = apt.copy()
        date_value = _normalize_appointment_dates(apt_copy)
        if date_value and start_date <= date_value <= end_date:
            result.append(apt_copy)
    return result


def _fetch_appointments_by_date_range_firebase(start_date: str, end_date: str) -> list:
    """Compatibility wrapper: use appointment_new range fetch implementation."""
    return _fetch_appointments_by_date_range_secondary_index(start_date, end_date)


def get_appointments_by_date_range_for_doctor(start_date_str, end_date_str, doctor_id=None):
    """Get appointments in [start_date_str, end_date_str] filtered by doctor's specialty in one pass."""
    try:
        start_date = (start_date_str or "").strip()
        end_date = (end_date_str or "").strip()
        if not start_date or not end_date:
            return []

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        all_appointments = []

        if doctor_id:
            doctor_variants = _doctor_key_variants(doctor_id)
            seen_ids = set()
            for day in _iter_iso_dates(start_date, end_date) or []:
                for doctor_key in doctor_variants:
                    day_node = db.child("appointment_new").child(doctor_key).child(day).get() or {}
                    if not isinstance(day_node, dict):
                        continue
                    for apt_id, apt_data in day_node.items():
                        if not apt_id or apt_id in seen_ids or not isinstance(apt_data, dict):
                            continue
                        seen_ids.add(apt_id)
                        apt = apt_data.copy()
                        apt["id"] = apt_id
                        if not apt.get("date"):
                            apt["date"] = day
                        if not apt.get("appointmentDate"):
                            apt["appointmentDate"] = apt.get("date")
                        if not apt.get("doctorID"):
                            apt["doctorID"] = doctor_key
                        all_appointments.append(apt)
        else:
            all_appointments = _fetch_appointments_by_date_range_firebase(start_date, end_date)

        doctor_specialty = None
        doctor_id_variants = set()
        if doctor_id:
            doctor_id_str = str(doctor_id).strip()
            doctor_id_variants.add(doctor_id_str)
            if doctor_id_str.startswith("doc_"):
                doctor_id_variants.add(doctor_id_str[4:])
            else:
                doctor_id_variants.add(f"doc_{doctor_id_str}")

            doctor = get_doctor_by_id(doctor_id)
            if doctor and doctor.get("specialtyID"):
                doctor_specialty = str(doctor.get("specialtyID")).strip().strip('"\'')

        doctor_cache = {}

        def appointment_specialty(apt):
            spec = apt.get("specialtyID")
            if spec:
                if isinstance(spec, str):
                    return spec.strip().strip('"\'')
                return spec

            did = apt.get("doctorID")
            if not did:
                return None

            if did in doctor_cache:
                cached = doctor_cache[did].get("specialtyID")
                if isinstance(cached, str):
                    return cached.strip().strip('"\'')
                return cached

            d = get_doctor_by_id(did)
            doctor_cache[did] = d or {}
            cached = doctor_cache[did].get("specialtyID")
            if isinstance(cached, str):
                return cached.strip().strip('"\'')
            return cached

        def doctor_matches(apt):
            """Return True if this appointment belongs to the logged-in doctor or their specialty."""
            apt_doctor_id = str(apt.get("doctorID") or "").strip()
            if apt_doctor_id and apt_doctor_id in doctor_id_variants:
                return True
            if doctor_specialty and appointment_specialty(apt) == doctor_specialty:
                return True
            return False

        # Filter by doctor/specialty (date filtering already done by Firebase query)
        date_range_appointments = []
        for apt in all_appointments:
            if not str(apt.get("date") or "").strip():
                continue

            if doctor_id:
                if not doctor_matches(apt):
                    continue

            date_range_appointments.append(apt)

        patient_ids = [apt.get("patientID", "") for apt in date_range_appointments if apt.get("patientID")]
        patients_map = get_patients_by_ids(patient_ids)

        for apt in date_range_appointments:
            pid = apt.get("patientID", "")
            patient = patients_map.get(pid)
            if patient:
                apt["patient_info"] = patient

        return date_range_appointments
    except Exception as e:
        print(f"[WARN] Firebase error get_appointments_by_date_range_for_doctor: {e}")
        return []


def get_appointments_by_time_slots_for_doctor(doctor_id=None):
    """Get time slots statistics filtered by doctor's specialty"""
    try:
        today = date_type.today().isoformat()
        all_appointments = get_all_appointments()
        today_appointments = [apt for apt in all_appointments if apt.get("date") == today]

        if doctor_id:
            doctor = get_doctor_by_id(doctor_id)
            doctor_specialty = doctor.get("specialtyID").strip() if doctor and doctor.get("specialtyID") else None
            if doctor_specialty:
                doctor_cache = {}
                def appointment_specialty(apt):
                    spec = apt.get("specialtyID")
                    if spec:
                        if isinstance(spec, str):
                            return spec.strip().strip('"\'')
                        return spec
                    did = apt.get("doctorID")
                    if not did:
                        return None
                    if did in doctor_cache:
                        cached = doctor_cache[did].get("specialtyID")
                        if isinstance(cached, str):
                            return cached.strip().strip('"\'')
                        return cached
                    d = get_doctor_by_id(did)
                    doctor_cache[did] = d or {}
                    cached = doctor_cache[did].get("specialtyID")
                    if isinstance(cached, str):
                        return cached.strip().strip('"\'')
                    return cached

                today_appointments = [
                    apt for apt in today_appointments
                    if appointment_specialty(apt) == doctor_specialty or apt.get("doctorID") == doctor_id
                ]

        time_slots = {
            "7:00-8:00": 0,
            "8:00-9:00": 0,
            "9:00-10:00": 0,
            "10:00-11:00": 0,
            "11:00-12:00": 0,
            "12:00-13:00": 0,
            "13:00-14:00": 0,
            "14:00-15:00": 0,
            "15:00-16:00": 0,
            "16:00-17:00": 0
        }

        for apt in today_appointments:
            t = apt.get("time", "")
            if not t:
                continue
            try:
                hour = int(t.split(":")[0])
                for slot_range in time_slots.keys():
                    start_hour = int(slot_range.split(":")[0])
                    end_hour = int(slot_range.split("-")[1].split(":")[0])
                    if start_hour <= hour < end_hour:
                        time_slots[slot_range] += 1
                        break
            except:
                pass

        return [{"time": slot, "count": count} for slot, count in time_slots.items()]
    except Exception as e:
        print(f"⚠️ Firebase error get_appointments_by_time_slots_for_doctor: {e}")
        return []


def get_daily_statistics_for_doctor(doctor_id=None, days=30):
    """Get daily statistics for the last N days"""
    try:
        from datetime import timedelta
        all_appointments = get_all_appointments()
        
        # Calculate start date
        today = date_type.today()
        start_date = today - timedelta(days=days-1)
        
        # Count appointments by date
        daily_stats = {}
        for current in [start_date + timedelta(days=x) for x in range(days)]:
            daily_stats[current.isoformat()] = 0
        
        # Filter and count
        for apt in all_appointments:
            apt_date = apt.get("date", "").strip() if isinstance(apt.get("date"), str) else ""
            if not apt_date:
                continue
            
            if doctor_id:
                if apt.get("doctorID") != doctor_id:
                    continue
            
            if apt_date in daily_stats:
                daily_stats[apt_date] += 1
        
        return [{"date": date, "count": count} for date, count in sorted(daily_stats.items())]
    except Exception as e:
        print(f"⚠️ Firebase error get_daily_statistics_for_doctor: {e}")
        return []


def get_weekly_statistics_for_doctor(doctor_id=None, weeks=12):
    """Get weekly statistics for the last N weeks"""
    try:
        from datetime import timedelta
        all_appointments = get_all_appointments()
        
        today = date_type.today()
        
        # Create week labels
        weekly_stats = {}
        for i in range(weeks):
            week_end = today - timedelta(weeks=i)
            week_start = week_end - timedelta(days=week_end.weekday())
            week_key = f"{week_start.isoformat()} - {week_end.isoformat()}"
            weekly_stats[week_key] = 0
        
        # Count by week
        for apt in all_appointments:
            apt_date_str = apt.get("date", "").strip() if isinstance(apt.get("date"), str) else ""
            if not apt_date_str:
                continue
            
            try:
                apt_date = date_type.fromisoformat(apt_date_str)
            except:
                continue
            
            if doctor_id and apt.get("doctorID") != doctor_id:
                continue
            
            # Find which week this date belongs to
            for week_key in weekly_stats.keys():
                week_start_str, week_end_str = week_key.split(" - ")
                week_start = date_type.fromisoformat(week_start_str)
                week_end = date_type.fromisoformat(week_end_str)
                
                if week_start <= apt_date <= week_end:
                    weekly_stats[week_key] += 1
                    break
        
        return [{"week": week, "count": count} for week, count in weekly_stats.items()]
    except Exception as e:
        print(f"⚠️ Firebase error get_weekly_statistics_for_doctor: {e}")
        return []


def get_monthly_statistics_for_doctor(doctor_id=None, months=12):
    """Get monthly statistics for the last N months"""
    try:
        from datetime import timedelta
        all_appointments = get_all_appointments()
        
        today = date_type.today()
        
        # Create month labels
        monthly_stats = {}
        for i in range(months):
            # Go back i months
            if today.month - i > 0:
                month_date = today.replace(month=today.month - i, day=1)
            else:
                month_date = today.replace(year=today.year - 1, month=12 + today.month - i, day=1)
            
            month_key = month_date.strftime("%Y-%m")
            monthly_stats[month_key] = 0
        
        # Count by month
        for apt in all_appointments:
            apt_date_str = apt.get("date", "").strip() if isinstance(apt.get("date"), str) else ""
            if not apt_date_str:
                continue
            
            try:
                apt_date = date_type.fromisoformat(apt_date_str)
            except:
                continue
            
            if doctor_id and apt.get("doctorID") != doctor_id:
                continue
            
            apt_month = apt_date.strftime("%Y-%m")
            if apt_month in monthly_stats:
                monthly_stats[apt_month] += 1
        
        # Sort by month
        return [{"month": month, "count": count} for month, count in sorted(monthly_stats.items(), reverse=True)]
    except Exception as e:
        print(f"⚠️ Firebase error get_monthly_statistics_for_doctor: {e}")
        return []


def get_yearly_statistics_for_doctor(doctor_id=None, years=5):
    """Get yearly statistics for the last N years"""
    try:
        all_appointments = get_all_appointments()
        
        today = date_type.today()
        
        # Create year labels
        yearly_stats = {}
        for i in range(years):
            year = today.year - i
            yearly_stats[str(year)] = 0
        
        # Count by year
        for apt in all_appointments:
            apt_date_str = apt.get("date", "").strip() if isinstance(apt.get("date"), str) else ""
            if not apt_date_str:
                continue
            
            try:
                apt_date = date_type.fromisoformat(apt_date_str)
            except:
                continue
            
            if doctor_id and apt.get("doctorID") != doctor_id:
                continue
            
            apt_year = str(apt_date.year)
            if apt_year in yearly_stats:
                yearly_stats[apt_year] += 1
        
        # Sort by year descending
        return [{"year": year, "count": count} for year, count in sorted(yearly_stats.items(), reverse=True)]
    except Exception as e:
        print(f"⚠️ Firebase error get_yearly_statistics_for_doctor: {e}")
        return []


def mark_appointment_arrived(appointment_id):
    """Helper to mark an appointment as arrived (Đã đến) and record arrival time.

    Also update the corresponding patient record with `lastArrival` timestamp
    so you know when they most recently showed up.
    """
    try:
        from datetime import datetime
        now_iso = datetime.now().isoformat()

        # update appointment status and add arrivalTime field
        updated = update_appointment(appointment_id, status="Đã đến", arrivalTime=now_iso)

        # also update patient record if we have an ID
        try:
            apt = get_appointment_by_id(appointment_id)
            pid = apt.get("patientID") if apt else None
            if pid:
                db.child("patients").child(pid).update({"lastArrival": now_iso})
        except Exception:
            pass

        return updated
    except Exception as e:
        print(f"⚠️ Firebase error mark_appointment_arrived: {e}")
        return None


def _iter_queue_buckets(queues_root):
    """Yield (queue_key, queue_tokens) pairs from the RTDB queues tree."""
    if not isinstance(queues_root, dict):
        return

    for queue_key, queue_tokens in queues_root.items():
        if isinstance(queue_tokens, dict):
            yield queue_key, queue_tokens


def set_appointment_priority(appointment_id: str, is_priority: bool, reason: str = "", priority_tier: str = None) -> bool:
    """
    Persist priority tier on an appointment and synchronize queue score.

    Priority model:
    - LOW (baseline): normal queue by FCFS.
    - MEDIUM: social priority (elderly, children, pregnant, disabled, veterans).
    - HIGH: medical priority (severe symptoms, post-op, complications).
    - CRITICAL: emergency, bypass regular waiting queue.

    Args:
        appointment_id: appointment ID to prioritize
        is_priority: whether to enable priority
        reason: priority reason/description (analyzed for keyword matching)
        priority_tier: explicit tier override (low/medium/high/critical) - if set, skips keyword analysis

    Stores under appointment.priority with tier metadata.
    Returns True on success, False on failure.
    """
    try:
        from datetime import datetime
        appointment_id = (appointment_id or "").strip()
        if not appointment_id:
            return False

        def _to_int(value, default=0):
            try:
                return int(value)
            except Exception:
                return default

        def _is_waiting_status(value) -> bool:
            text = _normalize_text_no_accents(str(value or ""))
            return text in {"waiting", "arrived", "da den", "dang cho", "dang cho kham", "cho kham"}

        def _priority_profile_from_reason(priority_reason: str) -> dict:
            text = _normalize_text_no_accents(priority_reason)

            # CRITICAL: emergency, life-threatening situations
            critical_keywords = {
                "shock",
                "dot quy",
                "nhoi mau co tim",
                "cap cu",
                "ngat",
                "mất ý thức",
                "kho tho nang",
                "khó thở nặng",
                "chan thuong",
                "chấn thương",
                "cap cuu",
                "cấp cứu",
            }
            # HIGH: medical urgency (illness/injury but stable)
            high_keywords = {
                "dau nhieu",
                "đau nhiều",
                "kho tho nhe",
                "khó thở nhẹ",
                "sot cao",
                "sốt cao",
                "sot",
                "sau phau thuat",
                "sau phẫu thuật",
                "hau phau thuat",
                "hậu phẫu thuật",
                "suy kiet",
                "suy kiệt",
                "yeu",
                "yếu",
                "nguy co chuyen nang",
                "nguy cơ chuyển nặng",
                "tim",
                "tieu duong",
                "tiểu đường",
                "huyet ap",
                "huyết áp",
            }
            # MEDIUM: social priority (vulnerable groups, need support)
            medium_keywords = {
                # Children
                "tre em",
                "trẻ em",
                "duoi 6 tuoi",
                "dưới 6 tuổi",
                "em be",
                "em bé",
                "be nho",
                "bé nhỏ",
                # Pregnant women
                "mang thai",
                "mang thai",
                "co thai",
                "có thai",
                "thanh phu",
                "thanh phụ",
                "phu nu mang thai",
                "phụ nữ mang thai",
                # Elderly
                "cao tuoi",
                "cao tuổi",
                "tren 80",
                "trên 80",
                "80 tuoi",
                "80 tuổi",
                "cao nien",
                "cao niên",
                "gia",
                "giả",
                "ong ba",
                "ông bà",
                # Disability
                "khuyet tat",
                "khuyết tật",
                "tan tat",
                "tàn tật",
                "tat nhan",
                "tật nhân",
                "khong may",
                "không may",
                # Veterans & service
                "co cong",
                "có công",
                "thuong binh",
                "thương binh",
                "liet si",
                "liệt sĩ",
                "liệt sĩ",
                "quân nhan",
                "quân nhân",
            }

            if any(keyword in text for keyword in critical_keywords):
                return {
                    "tier": "critical",
                    "label": "Priority 4 - Cấp cứu",
                    "code": "P4_CRITICAL",
                    "boost": 220,
                    "type": "critical",
                }

            if any(keyword in text for keyword in high_keywords):
                return {
                    "tier": "high",
                    "label": "Priority 3 - Ưu tiên y khoa",
                    "code": "P3_HIGH",
                    "boost": 140,
                    "type": "medical",
                }

            if any(keyword in text for keyword in medium_keywords):
                return {
                    "tier": "medium",
                    "label": "Priority 2 - Ưu tiên xã hội",
                    "code": "P2_MEDIUM",
                    "boost": 80,
                    "type": "social",
                }

            return {
                "tier": "medium",
                "label": "Priority 2 - Ưu tiên xã hội",
                "code": "P2_MEDIUM",
                "boost": 80,
                "type": "social",
            }

        def _apply_queue_priority_score() -> bool:
            queues_root = db.child("queues").get() or {}
            if not isinstance(queues_root, dict):
                return False

            # Use explicit tier if provided, otherwise infer from reason
            if priority_tier and str(priority_tier).strip().lower() in {"low", "medium", "high", "critical"}:
                tier_value = str(priority_tier).strip().lower()
                tier_map = {
                    "low": {
                        "tier": "low",
                        "label": "Priority 1 - Bình thường",
                        "code": "P1_LOW",
                        "boost": 0,
                        "type": "normal",
                    },
                    "medium": {
                        "tier": "medium",
                        "label": "Priority 2 - Ưu tiên xã hội",
                        "code": "P2_MEDIUM",
                        "boost": 80,
                        "type": "social",
                    },
                    "high": {
                        "tier": "high",
                        "label": "Priority 3 - Ưu tiên y khoa",
                        "code": "P3_HIGH",
                        "boost": 140,
                        "type": "medical",
                    },
                    "critical": {
                        "tier": "critical",
                        "label": "Priority 4 - Cấp cứu",
                        "code": "P4_CRITICAL",
                        "boost": 220,
                        "type": "critical",
                    },
                }
                priority_profile = tier_map[tier_value]
            else:
                priority_profile = _priority_profile_from_reason(reason)
            matched = False

            def _looks_like_token_bucket(node):
                if not isinstance(node, dict) or not node:
                    return False
                values = list(node.values())
                if not all(isinstance(v, dict) for v in values):
                    return False
                return any(
                    bool(v.get("appointmentId") or v.get("appointmentID") or v.get("queueNumber"))
                    for v in values
                )

            def _walk(node, path_parts):
                nonlocal matched
                if not isinstance(node, dict):
                    return

                if _looks_like_token_bucket(node):
                    target_token_id = None
                    working_tokens = {}

                    for token_id, token_data in node.items():
                        if not isinstance(token_data, dict):
                            continue

                        token_copy = token_data.copy()
                        token_appointment_id = str(
                            token_copy.get("appointmentId")
                            or token_copy.get("appointmentID")
                            or ""
                        ).strip()

                        if token_appointment_id == appointment_id:
                            target_token_id = token_id

                        if token_copy.get("basePriorityLevel") in (None, ""):
                            token_copy["basePriorityLevel"] = _to_int(token_copy.get("priorityLevel"), 50)

                        working_tokens[token_id] = token_copy

                    if not target_token_id:
                        return

                    matched = True
                    target_token = working_tokens[target_token_id]
                    base_level = _to_int(target_token.get("basePriorityLevel"), 50)

                    if is_priority:
                        target_token["priorityLevel"] = base_level + priority_profile["boost"]
                        target_token["priorityType"] = priority_profile["type"]
                        target_token["priorityReason"] = (reason or "").strip()
                        target_token["priorityTier"] = priority_profile["tier"]
                        target_token["priorityCode"] = priority_profile["code"]
                        target_token["priorityLabel"] = priority_profile["label"]

                        # CRITICAL: move out of regular waiting flow.
                        if priority_profile["tier"] == "critical":
                            if _is_waiting_status(target_token.get("status")):
                                target_token["preEmergencyStatus"] = target_token.get("status")
                            target_token["status"] = "emergency"
                            target_token["queueStatus"] = "emergency"
                    else:
                        # Bỏ ưu tiên: reset về baseline và xóa các field priority dư thừa
                        target_token["priorityLevel"] = base_level
                        target_token["priorityType"] = "normal"
                        # Xóa các field priority cũ để không còn lưu trong RTDB
                        for field in ("priorityReason", "priorityTier", "priorityCode", "priorityLabel"):
                            if field in target_token:
                                target_token.pop(field, None)
                        if str(target_token.get("status") or "").strip().lower() == "emergency":
                            target_token["status"] = target_token.get("preEmergencyStatus") or "waiting"
                            target_token["queueStatus"] = target_token.get("status")
                            target_token.pop("preEmergencyStatus", None)

                    # Capture each token's ORIGINAL queue number on first touch.
                    # This is the immutable position the patient gets when they
                    # check in (FCFS) and is what we sort by when priority is
                    # neutral. Toggling priority NEVER changes this value, so a
                    # patient who is prioritised and then un-prioritised falls
                    # back into their original spot without disturbing other
                    # patients' numbers.
                    for token_id, token_payload in working_tokens.items():
                        if token_payload.get("originalQueueNumber") in (None, "", 0):
                            existing_qn = _to_int(token_payload.get("queueNumber"), 0)
                            if existing_qn > 0:
                                token_payload["originalQueueNumber"] = existing_qn

                    def _rank(item):
                        _, token = item
                        original_qn = _to_int(token.get("originalQueueNumber"), 0)
                        return (
                            -_to_int(token.get("priorityLevel"), 0),
                            original_qn if original_qn > 0 else _to_int(token.get("queueNumber"), 10**9),
                            _to_int(token.get("arrivedAt"), 10**15),
                        )

                    emergency_items = []
                    normal_items = []
                    for token_id, token_payload in working_tokens.items():
                        if str(token_payload.get("status") or "").strip().lower() == "emergency":
                            emergency_items.append((token_id, token_payload))
                        else:
                            normal_items.append((token_id, token_payload))

                    sorted_items = sorted(normal_items, key=_rank)
                    waiting_count = 0

                    def _queue_bucket_ref(parts):
                        ref = db.child("queues")
                        for part in parts:
                            ref = ref.child(str(part))
                        return ref

                    bucket_ref = _queue_bucket_ref(path_parts)

                    # IMPORTANT: only assign a NEW queueNumber to tokens that
                    # do not yet have an originalQueueNumber recorded. For all
                    # other tokens we keep their original physical number so
                    # the patient display screen never sees their number jump
                    # around when an unrelated patient is prioritised.
                    next_unassigned = max(
                        (
                            _to_int(t.get("originalQueueNumber"), 0)
                            for _, t in sorted_items
                        ),
                        default=0,
                    )

                    for new_no_idx, (token_id, token_payload) in enumerate(sorted_items, start=1):
                        if not token_payload.get("originalQueueNumber"):
                            next_unassigned += 1
                            token_payload["originalQueueNumber"] = next_unassigned
                            token_payload["queueNumber"] = next_unassigned
                        else:
                            token_payload["queueNumber"] = token_payload["originalQueueNumber"]
                        if _is_waiting_status(token_payload.get("status")):
                            waiting_count += 1
                        bucket_ref.child(token_id).set(token_payload)

                    # Keep emergency tokens in the bucket but outside normal numbering.
                    for token_id, token_payload in emergency_items:
                        token_payload["queueNumber"] = 0
                        bucket_ref.child(token_id).set(token_payload)

                    # queue_meta canonical path: queue_meta/{doctor}/{date}
                    if len(path_parts) >= 2:
                        try:
                            db.child("queue_meta").child(path_parts[0]).child(path_parts[1]).update({
                                "lastQueueNumber": max(
                                    (_to_int(t.get("queueNumber"), 0) for _, t in sorted_items),
                                    default=0,
                                ),
                                "waitingCount": waiting_count,
                            })
                        except Exception:
                            pass
                    return

                for key, value in node.items():
                    if isinstance(key, str):
                        _walk(value, path_parts + [key])

            _walk(queues_root, [])

            return matched

        priority_profile = _priority_profile_from_reason(reason) if is_priority else {
            "tier": "low",
            "label": "Priority 1 - Bình thường",
            "code": "P1_LOW",
        }

        if is_priority:
            priority_payload = {
                "status": True,
                "reason": (reason or "").strip(),
                "setAt": datetime.now().isoformat(),
                "tier": priority_profile["tier"],
                "code": priority_profile["code"],
                "label": priority_profile["label"],
            }
            updated_apt = update_appointment(appointment_id, priority=priority_payload)
        else:
            # Bỏ ưu tiên: xóa hoàn toàn field priority khỏi RTDB thay vì set status=False
            try:
                target_apt = get_appointment_by_id(appointment_id)
                if not target_apt:
                    return False

                doctor_id = str(target_apt.get("doctorID") or "").strip()
                day_key = _normalize_appointment_day(target_apt.get("date") or target_apt.get("appointmentDate"))
                if doctor_id and day_key:
                    db.child("appointment_new").child(doctor_id).child(day_key).child(appointment_id).child("priority").delete()
                _apt_cache_invalidate(appointment_id)
                updated_apt = get_appointment_by_id(appointment_id)
            except Exception as del_err:
                print(f"[WARN] Failed to delete priority for {appointment_id}: {del_err}")
                return False

        if not updated_apt:
            return False

        try:
            _apply_queue_priority_score()
        except Exception as queue_err:
            print(f"[WARN] Queue priority update failed for {appointment_id}: {queue_err}")

        return True
    except Exception as e:
        print(f"[WARN] Firebase error set_appointment_priority: {e}")
        return False
