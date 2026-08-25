from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.cache import cache
from urllib.parse import urlencode
from datetime import date, timedelta, datetime
from time import monotonic
import time
from pathlib import Path
import threading
import uuid
import asyncio
import re
import hashlib
import json
import unicodedata
from django.utils import timezone
from services.firebase import db

from services.RTDB_utils import (
    create_walk_in_appointment,
    doctor_can_access_appointment,
    doctor_has_related_appointment,
    get_all_appointments,
    get_all_hospitals,
    get_all_specialties,
    get_doctor_by_id,
    get_patient_by_id,
    get_patient_medical_records_for_doctor,
    get_patients_by_ids,
    get_specialty_by_id,
    mark_appointment_arrived,
    mark_scheduled_appointments_no_show,
    set_appointment_priority,
)
from services.queue_notifications import notify_queue_advance


def _parse_selected_date(selected_date_str):

    if selected_date_str:
        try:
            return date.fromisoformat(selected_date_str)
        except Exception:
            try:
                return datetime.strptime(
                    selected_date_str, "%d/%m/%Y"
                ).date()
            except Exception:
                return date.today()

    return date.today()


def _normalize_search_text(value):
    raw = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return raw.replace("đ", "d")

def _extract_birthdate(patient):
    for key in ("birthdate", "dateOfBirth", "birthDate", "dob", "birthday"):
        value = patient.get(key)
        if value not in (None, ""):
            return value
    return ""


def _normalize_session(session_value, time_value=""):
    raw = str(session_value or "").strip().lower()
    normalized_raw = unicodedata.normalize("NFKD", raw)
    normalized_raw = "".join(ch for ch in normalized_raw if not unicodedata.combining(ch))
    normalized_raw = normalized_raw.replace("đ", "d")

    if normalized_raw in {"1", "morning", "buoi sang", "sang"}:
        return "morning", "Buổi sáng", 0

    if normalized_raw in {"2", "afternoon", "affternoon", "buoi chieu", "chieu"}:
        return "afternoon", "Buổi chiều", 1

    try:
        hour = int(str(time_value or "").strip().split(":")[0])
    except Exception:
        return "other", "Ngoài khung giờ", 2

    if 7 <= hour < 12:
        return "morning", "Buổi sáng", 0

    if 12 <= hour < 17:
        return "afternoon", "Buổi chiều", 1

    return "other", "Ngoài khung giờ", 2


def _build_priority_key(appointment_id="", patient_id="", session_key=""):
    appointment_key = str(appointment_id or "").strip()
    if appointment_key:
        return f"appointment:{appointment_key}"

    patient_key = str(patient_id or "").strip()
    session_part = str(session_key or "").strip().lower()
    if patient_key and session_part:
        return f"patient:{patient_key}:{session_part}"

    return ""


_DASHBOARD_POLL_CACHE = {}
_DASHBOARD_POLL_CACHE_TTL_SECONDS = 1.5  # well below the 5 s poll interval to keep latency low
_DASHBOARD_VERSION_TTL_SECONDS = int(getattr(settings, "DASHBOARD_VERSION_TTL_SECONDS", 2))
_DASHBOARD_SNAPSHOT_TTL_SECONDS = int(getattr(settings, "DASHBOARD_SNAPSHOT_TTL_SECONDS", 10))

_TTS_CACHE_DIR = Path(settings.BASE_DIR) / "static" / "generated_tts"
_TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_TTS_FILE_LOCKS = {}
_TTS_FILE_LOCKS_GUARD = threading.Lock()
_TTS_VOICE_ID = "vi-VN-HoaiMyNeural"
_TTS_RATE = "-20%"
_TTS_CACHE_VERSION = "tts" + hashlib.sha1(
    f"{_TTS_VOICE_ID}|{_TTS_RATE}".encode("utf-8", errors="ignore")
).hexdigest()[:8]


def _get_tts_file_lock(digest):
    with _TTS_FILE_LOCKS_GUARD:
        if digest not in _TTS_FILE_LOCKS:
            _TTS_FILE_LOCKS[digest] = threading.Lock()
        return _TTS_FILE_LOCKS[digest]


def _build_tts_audio_url(filename):
    static_prefix = '/' + str(settings.STATIC_URL).strip('/') + '/'
    return f"{static_prefix}generated_tts/{filename}"


def _safe_tts_name(name):
    cleaned = " ".join(str(name or "").split()).strip()
    if not cleaned:
        cleaned = "ABC"
    return cleaned


def _tts_text_pair(patient_name, queue_position=""):
    safe_name = _safe_tts_name(patient_name)
    safe_queue_position = str(queue_position or "").strip()
    if safe_queue_position:
        call_text = f"Mời bệnh nhân số {safe_queue_position}, {safe_name} vào phòng khám"
        remind_text = f"Xin nhắc lại mời bệnh nhân số {safe_queue_position}, {safe_name.upper()} vào phòng khám"
    else:
        call_text = f"Mời bệnh nhân {safe_name} vào phòng khám"
        remind_text = f"Xin nhắc lại mời bệnh nhân {safe_name.upper()} vào phòng khám"
    return call_text, remind_text


def _tts_filenames_for_appointment(appointment_id):
    apt = str(appointment_id or "").strip()
    if apt:
        token = re.sub(r"[^a-zA-Z0-9_-]+", "_", apt)
    else:
        token = f"anon_{uuid.uuid4().hex}"
    return (
        f"{token}_{_TTS_CACHE_VERSION}_call.mp3",
        f"{token}_{_TTS_CACHE_VERSION}_remind.mp3",
    )


def _write_edge_tts_mp3(text, out_path):
    try:
        import edge_tts
    except ImportError as e:
        raise RuntimeError(
            "No module named 'edge_tts'. Please install package: pip install edge-tts"
        ) from e

    tmp_path = _TTS_CACHE_DIR / f"{out_path.stem}.{uuid.uuid4().hex}.tmp"
    try:
        async def _synthesize_to_file():
            communicate = edge_tts.Communicate(
                text,
                voice=_TTS_VOICE_ID,
                rate=_TTS_RATE,
            )
            with open(tmp_path, "wb") as out_f:
                async for chunk in communicate.stream():
                    if chunk.get("type") == "audio":
                        out_f.write(chunk.get("data", b""))

        asyncio.run(_synthesize_to_file())

        if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
            raise RuntimeError("Edge TTS returned empty audio stream")

        tmp_path.replace(out_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def _ensure_tts_files_for_appointment(appointment_id, patient_name, queue_position=""):
    call_text, remind_text = _tts_text_pair(patient_name, queue_position)
    call_file, remind_file = _tts_filenames_for_appointment(appointment_id)
    call_path = _TTS_CACHE_DIR / call_file
    remind_path = _TTS_CACHE_DIR / remind_file

    digest = hashlib.sha1(str(appointment_id or call_text).encode("utf-8", errors="ignore")).hexdigest()
    lock = _get_tts_file_lock(digest)
    with lock:
        if not call_path.exists() or call_path.stat().st_size <= 0:
            _write_edge_tts_mp3(call_text, call_path)
        if not remind_path.exists() or remind_path.stat().st_size <= 0:
            _write_edge_tts_mp3(remind_text, remind_path)

    return {
        "call_filename": call_file,
        "call_url": _build_tts_audio_url(call_file),
        "remind_filename": remind_file,
        "remind_url": _build_tts_audio_url(remind_file),
        "call_text": call_text,
        "remind_text": remind_text,
    }


def _cleanup_tts_files_for_appointment(appointment_id):
    call_file, remind_file = _tts_filenames_for_appointment(appointment_id)
    for filename in (call_file, remind_file):
        path = _TTS_CACHE_DIR / filename
        if path.exists():
            try:
                path.unlink()
            except Exception as e:
                print(f"⚠️ TTS cleanup failed for {filename}: {e}")


_TTS_STALE_CLEANUP_LAST_RUN = 0.0
_TTS_STALE_CLEANUP_INTERVAL_SECONDS = 3600  # Run at most once per hour
_TTS_STALE_MAX_AGE_SECONDS = 24 * 3600  # Delete files older than 24 hours


def _cleanup_stale_tts_files():
    """Remove TTS audio files older than 24 hours. Called periodically to prevent disk buildup."""
    global _TTS_STALE_CLEANUP_LAST_RUN
    now = monotonic()
    if (now - _TTS_STALE_CLEANUP_LAST_RUN) < _TTS_STALE_CLEANUP_INTERVAL_SECONDS:
        return
    _TTS_STALE_CLEANUP_LAST_RUN = now

    try:
        import time as _time
        current_time = _time.time()
        removed = 0
        for path in _TTS_CACHE_DIR.glob("*.mp3"):
            try:
                file_age = current_time - path.stat().st_mtime
                if file_age > _TTS_STALE_MAX_AGE_SECONDS:
                    path.unlink()
                    removed += 1
            except Exception:
                pass
        if removed:
            print(f"[INFO] TTS cleanup: removed {removed} stale audio files (>24h old)")
    except Exception as e:
        print(f"⚠️ TTS stale cleanup error: {e}")


def _get_dashboard_context_cached(request, selected_date):
    """Short-lived cache to avoid rebuilding identical dashboard payloads under concurrent polling."""
    doctor_id = request.session.get("doctor_id") or ""
    cache_key = (doctor_id, selected_date.isoformat())
    now = monotonic()

    cached = _DASHBOARD_POLL_CACHE.get(cache_key)
    if cached and (now - cached["ts"]) <= _DASHBOARD_POLL_CACHE_TTL_SECONDS:
        return cached["context"]

    context = _build_dashboard_context(request, selected_date, "")
    _DASHBOARD_POLL_CACHE[cache_key] = {"ts": now, "context": context}

    # Keep cache bounded in-process.
    if len(_DASHBOARD_POLL_CACHE) > 64:
        oldest_key = min(_DASHBOARD_POLL_CACHE, key=lambda k: _DASHBOARD_POLL_CACHE[k]["ts"])
        _DASHBOARD_POLL_CACHE.pop(oldest_key, None)

    return context


def _build_dashboard_snapshot_key(context):
    """Build a compact key for change detection between polling intervals."""
    stats = context.get("dashboard_stats", {})
    appointments = context.get("all_today_appointments", [])

    chunks = [
        str(stats.get("total", 0)),
        str(stats.get("waiting", 0)),
        str(stats.get("scheduled", 0)),
        str(stats.get("completed", 0)),
        str(stats.get("morning", 0)),
        str(stats.get("afternoon", 0)),
    ]

    for apt in appointments:
        chunks.extend([
            str(apt.get("appointment_id", "")),
            str(apt.get("status_key", "")),
            str(apt.get("isPriority", False)),
            str(apt.get("prioritySetAt", "")),
            str(apt.get("time_display", "")),
            str(apt.get("name", "")),
            str(apt.get("session_key", "")),
        ])

    raw = "|".join(chunks).encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()


def _dashboard_version_cache_key(doctor_id, selected_date_iso):
    return f"dashboard:version:{doctor_id}:{selected_date_iso}"


def _dashboard_snapshot_cache_key(doctor_id, selected_date_iso, version):
    return f"dashboard:snapshot:{doctor_id}:{selected_date_iso}:{version}"


def _dashboard_stats_cache_key(doctor_id, selected_date_iso, version):
    return f"dashboard:stats:{doctor_id}:{selected_date_iso}:{version}"


def invalidate_dashboard_cache(doctor_id="", selected_date_iso=""):
    """Invalidate cached dashboard payloads so the next poll rebuilds from Firebase.

    Call this after any mutation that affects the dashboard (check-in, completion,
    walk-in creation, priority change, etc.).
    """
    doctor_id = str(doctor_id or "").strip()
    if not doctor_id or not selected_date_iso:
        return

    version_key = _dashboard_version_cache_key(doctor_id, selected_date_iso)
    cached_version = str(cache.get(version_key) or '').strip()
    cache.delete(version_key)
    if cached_version:
        cache.delete(_dashboard_snapshot_cache_key(doctor_id, selected_date_iso, cached_version))
        cache.delete(_dashboard_stats_cache_key(doctor_id, selected_date_iso, cached_version))

    # Also clear the in-process per-doctor context cache.
    cache_key = (doctor_id, selected_date_iso)
    _DASHBOARD_POLL_CACHE.pop(cache_key, None)


def _build_dashboard_poll_payload(selected_date_iso, context):
    appointments = []
    for apt in context.get("all_today_appointments", []):
        appointments.append({
            'appointment_id': apt.get('appointment_id', ''),
            'patient_id': apt.get('patient_id', ''),
            'name': apt.get('name', ''),
            'status_key': apt.get('status_key', ''),
            'status': apt.get('status', ''),
            'session_key': apt.get('session_key', ''),
            'session_label': apt.get('session_label', ''),
            'time': apt.get('time', ''),
            'time_display': apt.get('time_display', ''),
            'isPriority': apt.get('isPriority', False),
            'priorityReason': apt.get('priorityReason', ''),
            'prioritySetAt': apt.get('prioritySetAt', ''),
            'phone': apt.get('phone', ''),
            'gender': apt.get('gender', ''),
            'age': apt.get('age', ''),
            'birthdate': apt.get('birthdate', ''),
            'summary_text': apt.get('summary_text', ''),
            'queue_key': apt.get('queue_key', ''),
            'queue_token_id': apt.get('queue_token_id', ''),
            'queue_position': apt.get('queue_position', ''),
            'queue_current_token': apt.get('queue_current_token', ''),
            'queue_total_tokens': apt.get('queue_total_tokens', ''),
        })

    payload = {
        'date': selected_date_iso,
        'stats': context.get('dashboard_stats', {}),
        'appointments': appointments,
    }
    return payload


def _doctor_key_variants(doctor_id=""):
    doctor_key = str(doctor_id or "").strip()
    if not doctor_key:
        return []

    variants = [doctor_key]
    if doctor_key.startswith("doc_"):
        variants.append(doctor_key[4:])
    else:
        variants.append(f"doc_{doctor_key}")

    seen = set()
    ordered = []
    for key in variants:
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _load_appointments_from_appointment_new(selected_date_iso, doctor_id=""):
    """Load appointments directly from appointment_new/{doctor_id}/{date}."""
    day_key = str(selected_date_iso or "").strip()
    doctor_keys = _doctor_key_variants(doctor_id)
    if not doctor_keys or not day_key:
        return []

    appointments = []
    seen_ids = set()

    for doctor_key in doctor_keys:
        try:
            day_node = db.child("appointment_new").child(doctor_key).child(day_key).get() or {}
        except Exception as e:
            print(f"⚠️ appointment_new load error: {e}")
            continue

        if not isinstance(day_node, dict):
            continue

        for apt_id, apt_data in day_node.items():
            appointment_id = str(apt_id or "").strip()
            if not appointment_id or appointment_id in seen_ids or not isinstance(apt_data, dict):
                continue

            seen_ids.add(appointment_id)
            apt_copy = apt_data.copy()
            apt_copy["id"] = appointment_id
            appointments.append(apt_copy)

    return appointments


def _load_queue_lookup_for_date(selected_date_iso, doctor_id=""):
    """Build appointmentID -> queue token/meta lookup for one date/doctor.
    
    Optimized: queries only queues/{doctor_key}/{date} instead of entire queues/ tree.
    """
    try:
        selected_date_iso = str(selected_date_iso or "").strip()
        doctor_key = str(doctor_id or "").strip()
        if not selected_date_iso:
            return {}

        # Build candidate doctor keys
        candidate_doctor_keys = []
        if doctor_key:
            candidate_doctor_keys.append(doctor_key)
            if doctor_key.startswith("doc_"):
                candidate_doctor_keys.append(doctor_key[4:])
            else:
                candidate_doctor_keys.append(f"doc_{doctor_key}")

        if not candidate_doctor_keys:
            return {}

        queue_lookup = {}

        for dk in candidate_doctor_keys:
            try:
                # Targeted query: only this doctor's queue for this date
                token_bucket = db.child("queues").child(dk).child(selected_date_iso).get() or {}
            except Exception:
                token_bucket = {}

            if not isinstance(token_bucket, dict):
                continue

            # Load meta for this bucket
            meta = {}
            try:
                meta_data = db.child("queue_meta").child(dk).child(selected_date_iso).get()
                if isinstance(meta_data, dict):
                    meta = meta_data
            except Exception:
                pass

            bucket_path = f"{dk}/{selected_date_iso}"

            for token_id, token_data in token_bucket.items():
                if not isinstance(token_data, dict):
                    continue

                appointment_id = str(
                    token_data.get("appointmentID")
                    or token_data.get("appointmentId")
                    or ""
                ).strip()
                if not appointment_id:
                    continue

                queue_lookup[appointment_id] = {
                    "queue_key": bucket_path,
                    "token_id": token_id,
                    "token": token_data,
                    "meta": meta,
                }

        return queue_lookup
    except Exception as e:
        print(f"⚠️ Queue lookup error: {e}")
        return {}


def _build_dashboard_context(request, selected_date, search_query=""):

    doctor_id = request.session.get("doctor_id")

    # Mark no-show only once per session transition (not on every poll).
    current_date = date.today()
    current_hour = timezone.localtime().hour
    noshow_cache_key = f"noshow_done:{doctor_id}:{selected_date.isoformat()}"

    if not cache.get(noshow_cache_key):
        if selected_date < current_date:
            mark_scheduled_appointments_no_show(selected_date.isoformat(), "morning", doctor_id)
            mark_scheduled_appointments_no_show(selected_date.isoformat(), "afternoon", doctor_id)
            cache.set(noshow_cache_key, True, timeout=3600)
        elif selected_date == current_date:
            if current_hour >= 12:
                mark_scheduled_appointments_no_show(selected_date.isoformat(), "morning", doctor_id)
            if current_hour >= 17:
                mark_scheduled_appointments_no_show(selected_date.isoformat(), "afternoon", doctor_id)
            # Short TTL so it re-checks when session transitions
            cache.set(noshow_cache_key, True, timeout=300)

    queue_lookup = _load_queue_lookup_for_date(selected_date.isoformat(), doctor_id)

    all_appointments = _load_appointments_from_appointment_new(
        selected_date.isoformat(),
        doctor_id,
    )

    patient_ids = list({
        apt.get("patientID")
        for apt in all_appointments
        if apt.get("patientID")
    })

    patients_map = get_patients_by_ids(patient_ids)

    search_query = (search_query or "").strip()
    search_query_normalized = search_query.lower()

    processed_appointments = []
    seen_appointment_keys = set()

    def _to_checkin_sort_value(*values):
        """Return comparable timestamp for FCFS ordering (smaller = earlier)."""
        for raw in values:
            if raw in (None, ""):
                continue

            if isinstance(raw, (int, float)):
                try:
                    value = int(raw)
                    if value > 10**12:
                        value = value // 1000
                    if value > 0:
                        return value
                except Exception:
                    pass

            text = str(raw).strip()
            if not text:
                continue

            if text.isdigit():
                try:
                    value = int(text)
                    if value > 10**12:
                        value = value // 1000
                    if value > 0:
                        return value
                except Exception:
                    pass

            try:
                dt_value = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return int(dt_value.timestamp())
            except Exception:
                pass

        return 10**15

    for apt in all_appointments:

        patient_id = apt.get("patientID", "")

        appointment_id = (
            apt.get("id")
            or apt.get("appointmentID")
            or patient_id
        )

        patient = patients_map.get(patient_id, {})

        apt["appointment_id"] = appointment_id
        apt["patient_id"] = patient_id

        status_key, status_label = normalize_status(
            apt.get("status", "")
        )

        apt["status_key"] = status_key
        apt["status"] = status_label

        queue_entry = queue_lookup.get(str(appointment_id).strip()) or {}
        queue_token = queue_entry.get("token") if isinstance(queue_entry, dict) else {}
        queue_meta = queue_entry.get("meta") if isinstance(queue_entry, dict) else {}
        if not isinstance(queue_token, dict):
            queue_token = {}
        if not isinstance(queue_meta, dict):
            queue_meta = {}

        apt["queue_key"] = queue_entry.get("queue_key", "") if isinstance(queue_entry, dict) else ""
        apt["queue_token_id"] = queue_entry.get("token_id", "") if isinstance(queue_entry, dict) else ""
        apt["queue_position"] = queue_token.get("position") or queue_token.get("queueNumber") or queue_token.get("number") or ""
        apt["queue_current_token"] = queue_meta.get("currentToken") or queue_meta.get("current_token") or queue_meta.get("currentlyServing") or ""
        apt["queue_total_tokens"] = queue_meta.get("totalTokens") or queue_meta.get("total_tokens") or queue_meta.get("waitingCount") or ""
        try:
            apt["queue_priority_level"] = int(queue_token.get("priorityLevel") or 0)
        except Exception:
            apt["queue_priority_level"] = 0

        use_queue_patient = status_key == "waiting" and bool(queue_token)

        queue_patient_name = (
            queue_token.get("patientName")
            or queue_token.get("name")
            or queue_token.get("fullName")
            or ""
        )
        queue_patient_phone = queue_token.get("phone") or queue_token.get("patientPhone") or ""
        queue_patient_gender = queue_token.get("gender") or queue_token.get("patientGender") or ""
        queue_patient_birthdate = _extract_birthdate(queue_token)

        apt["name"] = (
            queue_patient_name if use_queue_patient else ""
        ) or patient.get("name") or apt.get("name") or "Bệnh nhân chưa rõ tên"

        apt["phone"] = (
            queue_patient_phone if use_queue_patient else ""
        ) or patient.get("phone", "")
        apt["gender"] = normalize_gender(
            (
                queue_patient_gender if use_queue_patient else ""
            ) or patient.get("gender", "")
        )
        apt["birthdate"] = (
            queue_patient_birthdate if use_queue_patient else ""
        ) or _extract_birthdate(patient)
        apt["age"] = calculate_age(apt["birthdate"])

        time_value = (apt.get("time") or "").strip()
        session_value = (
            apt.get("session")
            or apt.get("appointmentSession")
            or apt.get("sessionID")
        )

        session_key, session_label, session_order = _normalize_session(
            session_value,
            time_value,
        )

        apt["session_key"] = session_key
        apt["session_label"] = session_label

        # Priority: read from RTDB appointment data (persistent, per-appointment).
        # Stored under appointments/{id}/priority as {"status", "reason", "setAt"}.
        # Naturally session-scoped because each appointment has its own ID.
        priority_data = apt.get("priority") or {}
        if isinstance(priority_data, dict):
            apt["isPriority"] = bool(priority_data.get("status", False))
            apt["priorityReason"] = priority_data.get("reason", "")
            apt["prioritySetAt"] = (priority_data.get("setAt") or "").strip()
        else:
            apt["isPriority"] = False
            apt["priorityReason"] = ""
            apt["prioritySetAt"] = ""

        # Keep priority_key for template compatibility.
        priority_key = _build_priority_key(
            appointment_id=appointment_id,
            patient_id=patient_id,
            session_key=session_key,
        )
        apt["priority_key"] = priority_key

        apt["time"] = time_value
        apt["time_display"] = time_value or session_label

        # Arrival time recorded at QR scan — used for FCFS ordering.
        arrival_time = (
            apt.get("checkedInAt")
            or apt.get("arrivalTime")
            or apt.get("arrivedAt")
            or queue_token.get("arrivedAt")
            or queue_token.get("checkedInAt")
            or ""
        )
        apt["arrivalTime"] = str(arrival_time or "").strip()
        checkin_sort = _to_checkin_sort_value(arrival_time)

        apt["status_order"] = {
            "waiting": 0,
            "scheduled": 1,
            "completed": 2,
            "cancelled": 3,
            "no_show": 4,
        }.get(status_key, 4)

        # Sort logic — per-session, FCFS + doctor-assigned priority:
        #
        # Bucket 0 → priority patients:
        #   sorted by -setAt (most recently prioritised = very front)
        #   tie-break: waiting before scheduled, then FCFS/appointment time
        # Bucket 1 → normal patients:
        #   waiting FCFS (by arrivalTime), then scheduled (by appointment time)
        # Bucket 2 → completed / cancelled / no_show
        #
        # Removing priority moves the patient back to bucket 1 automatically;
        # their natural position is preserved because arrivalTime/appointment
        # time never change when priority is toggled.
        if status_key in ("completed", "cancelled", "no_show"):
            sort_order = (
                session_order,
                2,
                apt["status_order"],
                time_value,
            )
        elif apt["isPriority"]:
            # Negate setAt so most-recently-prioritised patient sorts first.
            # ISO strings are lexicographically comparable; inverting them gives
            # descending order without converting to a numeric type.
            set_at = apt["prioritySetAt"]
            neg_set_at = tuple(~ord(c) for c in set_at) if set_at else (0,)
            sort_order = (
                session_order,
                0,           # priority bucket
                -(apt.get("queue_priority_level") or 0),
                neg_set_at,  # most-recently-set first
                apt["status_order"],
                checkin_sort,
                time_value,
            )
        else:
            sort_order = (
                session_order,
                1,                    # normal bucket
                0,                    # ignore queue_priority_level when not priority
                (),                   # placeholder so tuple length matches
                apt["status_order"],  # waiting(0) before scheduled(1)
                checkin_sort,
                time_value,
            )
        apt["sort_order"] = sort_order

        apt["summary_text"] = (
            apt.get("symptoms")
            or apt.get("diagnosis")
            or apt.get("advice")
            or apt.get("priorityReason")
            or "Chưa có mô tả triệu chứng."
        )

        if search_query_normalized:

            searchable_values = (
                apt.get("name", ""),
                apt.get("phone", ""),
                apt.get("summary_text", ""),
            )

            if not any(
                search_query_normalized in str(v).lower()
                for v in searchable_values
            ):
                continue

        dedupe_key = (
            appointment_id
            or f"{patient_id}|{selected_date.isoformat()}|{time_value}|{status_key}"
        )
        if dedupe_key in seen_appointment_keys:
            continue

        seen_appointment_keys.add(dedupe_key)
        processed_appointments.append(apt)

    processed_appointments.sort(
        key=lambda item: item["sort_order"]
    )

    morning_appointments = [
        apt for apt in processed_appointments
        if apt.get("session_key") == "morning"
    ]

    afternoon_appointments = [
        apt for apt in processed_appointments
        if apt.get("session_key") == "afternoon"
    ]

    waiting_list = [
        apt.get("name", "")
        for apt in processed_appointments
        if apt.get("status_key") == "waiting"
    ]

    featured_appointments = [
        apt for apt in processed_appointments
        if apt.get("isPriority") or apt.get("status_key") == "waiting"
    ][:4]

    if not featured_appointments:
        featured_appointments = processed_appointments[:4]

    # Next patient = first priority patient OR first waiting patient in sorted order.
    # processed_appointments is already sorted so the first non-completed/cancelled/no_show
    # entry that is either waiting or priority is the correct "next up".
    next_waiting_appointment = next(
        (
            apt for apt in processed_appointments
            if apt.get("status_key") == "waiting" or apt.get("isPriority")
            if apt.get("status_key") not in ("completed", "cancelled", "no_show")
        ),
        None,
    )

    dashboard_stats = {

        "total": len(processed_appointments),

        "completed": sum(
            1 for apt in processed_appointments
            if apt.get("status_key") == "completed"
        ),

        "waiting": sum(
            1 for apt in processed_appointments
            if apt.get("status_key") == "waiting"
        ),

        "scheduled": sum(
            1 for apt in processed_appointments
            if apt.get("status_key") == "scheduled"
        ),

        "priority": sum(
            1 for apt in processed_appointments
            if apt.get("isPriority")
        ),

        "morning": len(morning_appointments),
        "afternoon": len(afternoon_appointments),
    }

    return {
        "morning_appointments": morning_appointments,
        "afternoon_appointments": afternoon_appointments,

        "all_today_appointments": processed_appointments,
        "featured_appointments": featured_appointments,
        "next_waiting_appointment": next_waiting_appointment,

        "waiting_list": waiting_list,

        "today": timezone.localdate(),

        "selected_date": selected_date,
        "selected_date_iso": selected_date.isoformat(),

        "search_query": search_query,

        "is_today": selected_date == timezone.localdate(),

        "dashboard_stats": dashboard_stats,
    }

# =========================
# UTIL FUNCTIONS
# =========================

def calculate_age(birthdate_str, ref_date=None):

    if not birthdate_str:
        return 0

    if isinstance(birthdate_str, (int, float)):
        try:
            timestamp = float(birthdate_str)
            if timestamp > 10**12:
                timestamp = timestamp / 1000.0
            dob = datetime.fromtimestamp(timestamp).date()
        except Exception:
            return 0
    else:
        raw_value = str(birthdate_str).strip()

        if not raw_value:
            return 0

        if raw_value.isdigit():
            try:
                timestamp = float(raw_value)
                if timestamp > 10**12:
                    timestamp = timestamp / 1000.0
                dob = datetime.fromtimestamp(timestamp).date()
            except Exception:
                return 0
        else:
            # Common payloads may include ISO datetime, keep only date part.
            raw_value = raw_value.replace("Z", "")
            if "T" in raw_value:
                raw_value = raw_value.split("T", 1)[0]
            if " " in raw_value:
                raw_value = raw_value.split(" ", 1)[0]

            parsed = None
            for fmt in (
                "%Y-%m-%d",
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%Y/%m/%d",
                "%m/%d/%Y",
            ):
                try:
                    parsed = datetime.strptime(raw_value, fmt).date()
                    break
                except ValueError:
                    continue

            if parsed is None:
                try:
                    parsed = date.fromisoformat(raw_value)
                except ValueError:
                    return 0

            dob = parsed

    ref_date = ref_date or date.today()

    age = ref_date.year - dob.year

    if (ref_date.month, ref_date.day) < (dob.month, dob.day):
        age -= 1

    return age if age >= 0 else 0


def normalize_gender(g):

    g = (g or "").lower()

    if g == "male":
        return "Nam"

    if g == "female":
        return "Nữ"

    return g


def normalize_status(status_value):

    normalized = unicodedata.normalize(
        "NFKD", (status_value or "").strip().lower()
    )

    normalized = "".join(
        ch for ch in normalized if not unicodedata.combining(ch)
    )

    normalized = normalized.replace("đ", "d")

    if normalized in {"scheduled", "chua den", "pending"}:
        return "scheduled", "Chưa đến"

    if normalized in {"waiting", "arrived", "da den", "dang cho kham", "dang kham"}:
        return "waiting", "Đã đến"

    if normalized in {"da kham", "completed", "complete"}:
        return "completed", "Đã khám"

    if normalized in {
        "no_show",
        "noshow",
        "no show",
        "vang",
        "vang mat",
        "qua hen",
    }:
        return "no_show", "Quá hẹn"

    if normalized in {
        "cancelled",
        "da huy",
        "qua han",
        "het han",
        "expired",
        "overdue",
        "lich da huy hoac qua han",
    }:
        return "cancelled", "Đã hủy"

    return "scheduled", status_value or "Chưa đến"


def _is_active_exam_session(appointment):
    """A valid session context means appointment is today and currently in waiting/exam flow."""
    if not isinstance(appointment, dict):
        return False

    raw_date = str(appointment.get("date") or "").strip()
    if not raw_date:
        return False

    try:
        apt_date = date.fromisoformat(raw_date)
    except Exception:
        return False

    status_key, _ = normalize_status(appointment.get("status", ""))
    return apt_date == date.today() and status_key == "waiting"


# =========================
# DASHBOARD POLL API
# =========================

def dashboard_poll_view(request):
    """JSON endpoint for real-time dashboard polling (no reload needed)."""
    if not request.session.get('doctor_id'):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    # Periodically clean up stale TTS files (at most once per hour, non-blocking).
    _cleanup_stale_tts_files()

    doctor_id = str(request.session.get('doctor_id') or '').strip()
    selected_date = _parse_selected_date(request.GET.get('date'))
    selected_date_iso = selected_date.isoformat()
    version_key = _dashboard_version_cache_key(doctor_id, selected_date_iso)
    client_snapshot_key = (request.GET.get('snapshot_key') or '').strip()

    # Flow: check dashboard_version (cache/Redis), same version => lightweight no-change response.
    cached_version = str(cache.get(version_key) or '').strip()
    if cached_version and client_snapshot_key and client_snapshot_key == cached_version:
        stats = cache.get(_dashboard_stats_cache_key(doctor_id, selected_date_iso, cached_version)) or {}
        return JsonResponse({
            'date': selected_date_iso,
            'stats': stats,
            'snapshot_key': cached_version,
            'changed': False,
        })

    # Different version => serve cached JSON snapshot if present (no context rebuild).
    if cached_version:
        cached_payload = cache.get(
            _dashboard_snapshot_cache_key(doctor_id, selected_date_iso, cached_version)
        )
        if isinstance(cached_payload, dict):
            return JsonResponse({
                'date': selected_date_iso,
                'stats': cached_payload.get('stats', {}),
                'snapshot_key': cached_version,
                'changed': True,
                'appointments': cached_payload.get('appointments', []),
            })

    # Cache miss path: build context once, store version + snapshot, then respond.
    context = _get_dashboard_context_cached(request, selected_date)
    payload = _build_dashboard_poll_payload(selected_date_iso, context)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    snapshot_key = hashlib.sha1(raw).hexdigest()
    cache.set(version_key, snapshot_key, timeout=_DASHBOARD_VERSION_TTL_SECONDS)
    cache.set(
        _dashboard_snapshot_cache_key(doctor_id, selected_date_iso, snapshot_key),
        payload,
        timeout=_DASHBOARD_SNAPSHOT_TTL_SECONDS,
    )
    cache.set(
        _dashboard_stats_cache_key(doctor_id, selected_date_iso, snapshot_key),
        payload.get('stats', {}),
        timeout=_DASHBOARD_SNAPSHOT_TTL_SECONDS,
    )

    if client_snapshot_key and client_snapshot_key == snapshot_key:
        return JsonResponse({
            'date': selected_date_iso,
            'stats': payload.get('stats', {}),
            'snapshot_key': snapshot_key,
            'changed': False,
        })

    return JsonResponse({
        'date': selected_date_iso,
        'stats': payload.get('stats', {}),
        'snapshot_key': snapshot_key,
        'changed': True,
        'appointments': payload.get('appointments', []),
    })


def appointment_detail_api_view(request, appointment_id):
    """Return detailed patient info for one appointment (lazy-loaded when modal opens)."""
    if not request.session.get('doctor_id'):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    appointment_id = (appointment_id or '').strip()
    if not appointment_id:
        return JsonResponse({'error': 'invalid'}, status=400)

    # Try to serve from the cached dashboard context to avoid an extra Firebase round-trip.
    selected_date = _parse_selected_date(request.GET.get('date'))
    cached_ctx = _get_dashboard_context_cached(request, selected_date)
    for apt in cached_ctx.get('all_today_appointments', []):
        if str(apt.get('appointment_id', '')) == appointment_id:
            return JsonResponse({
                'phone': apt.get('phone', ''),
                'gender': apt.get('gender', ''),
                'age': apt.get('age', 0),
                'birthdate': apt.get('birthdate', ''),
                'summary_text': apt.get('summary_text', ''),
                'priorityReason': apt.get('priorityReason', ''),
            })

    # Fallback: fetch directly from Firebase (e.g. historical date not in cache).
    from services.RTDB_utils import get_appointment_with_patient_info
    apt_data = get_appointment_with_patient_info(appointment_id)
    if not apt_data:
        return JsonResponse({'error': 'not found'}, status=404)

    patient = apt_data.get('patient_info', {}) or {}
    priority_data = apt_data.get('priority', {}) or {}
    return JsonResponse({
        'phone': patient.get('phone', ''),
        'gender': normalize_gender(patient.get('gender', '')),
        'age': calculate_age(_extract_birthdate(patient)),
        'birthdate': _extract_birthdate(patient),
        'summary_text': (
            apt_data.get('symptoms')
            or apt_data.get('diagnosis')
            or apt_data.get('advice')
            or ''
        ),
        'priorityReason': priority_data.get('reason', ''),
    })


@csrf_exempt
def dashboard_tts_prefetch_view(request):
    """Create and cache call/reminder audio using Edge TTS HoaiMy voice."""
    if not request.session.get('doctor_id'):
        return JsonResponse({'success': False, 'message': 'unauthorized'}, status=401)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

    try:
        payload = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    appointment_id = str(payload.get('appointment_id') or '').strip()
    patient_name = str(payload.get('name') or '').strip()
    queue_position = payload.get('queue_position', '')
    if not patient_name:
        patient_name = 'ABC'

    try:
        tts_data = _ensure_tts_files_for_appointment(appointment_id, patient_name, queue_position)
        return JsonResponse({
            'success': True,
            'audio_url': tts_data['call_url'],
            'remind_audio_url': tts_data['remind_url'],
            'text': tts_data['call_text'],
            'remind_text': tts_data['remind_text'],
        })
    except Exception as e:
        print(f"⚠️ dashboard_tts_prefetch_view error: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def dashboard_debug_view(request):
    """Debug endpoint — dumps raw Firebase appointments + processed context for a date."""
    if not request.session.get('doctor_id'):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    selected_date = _parse_selected_date(request.GET.get('date'))
    doctor_id = request.session.get('doctor_id')

    # Raw Firebase data from appointment_new/{doctor}/{date}
    raw_appointments = _load_appointments_from_appointment_new(selected_date.isoformat(), doctor_id)

    raw_dump = []
    for apt in raw_appointments:
        raw_dump.append({
            'id': apt.get('id') or apt.get('appointmentID') or '',
            'patientID': apt.get('patientID', ''),
            'date': apt.get('date') or apt.get('appointmentDate') or '',
            'time': apt.get('time', ''),
            'session': apt.get('session') or apt.get('appointmentSession') or '',
            'status_raw': apt.get('status', ''),
            'doctorID': apt.get('doctorID', ''),
        })

    # Processed context
    context = _build_dashboard_context(request, selected_date)
    processed_dump = []
    for apt in context['all_today_appointments']:
        processed_dump.append({
            'appointment_id': apt.get('appointment_id', ''),
            'name': apt.get('name', ''),
            'time': apt.get('time', ''),
            'session_key': apt.get('session_key', ''),
            'session_label': apt.get('session_label', ''),
            'status_key': apt.get('status_key', ''),
            'status': apt.get('status', ''),
            'isPriority': apt.get('isPriority', False),
        })

    return JsonResponse({
        'date': selected_date.isoformat(),
        'doctor_id': doctor_id,
        'raw_count': len(raw_dump),
        'processed_count': len(processed_dump),
        'raw_appointments': raw_dump,
        'processed_appointments': processed_dump,
        'stats': context['dashboard_stats'],
    }, json_dumps_params={'ensure_ascii': False, 'indent': 2})


# =========================
# DASHBOARD PAGE
# =========================

def _build_shell_context(request, selected_date, search_query=""):
    """Return an instant, zero-Firebase context.  Appointments are loaded via the first AJAX poll."""
    today = timezone.localdate()
    is_today = (selected_date == today)
    return {
        "selected_date": selected_date,
        "selected_date_iso": selected_date.isoformat(),
        "is_today": is_today,
        "today_iso": today.isoformat(),
        "search_query": (search_query or "").strip(),
        "all_today_appointments": [],
        "dashboard_stats": {
            "total": 0,
            "waiting": 0,
            "completed": 0,
            "scheduled": 0,
            "morning": 0,
            "afternoon": 0,
        },
        "initial_snapshot_key": "",
    }


def _render_dashboard_page(request):
    selected_date = _parse_selected_date(request.GET.get("date"))
    context = _build_shell_context(
        request,
        selected_date,
        request.GET.get("search", ""),
    )
    return render(
        request,
        "appointments/dashboard.html",
        context
    )


def _get_patient_display_session_scope(selected_date):
    """Patient display shows only the active session for today; other dates show all."""
    if selected_date != timezone.localdate():
        return "all"

    current_hour = timezone.localtime().hour
    return "afternoon" if current_hour >= 12 else "morning"


def _is_patient_display_arrived(apt):
    """Accept both normalized and raw arrived/waiting status values for patient display."""
    if not isinstance(apt, dict):
        return False

    status_key = str(apt.get("status_key") or "").strip().lower()
    if status_key == "waiting":
        return True

    raw_status = str(apt.get("status") or "").strip()
    normalized, _ = normalize_status(raw_status)
    return normalized == "waiting"


def _is_queue_waiting_status(raw_status):
    text = str(raw_status or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch)).replace("đ", "d")
    return normalized in {
        "waiting",
        "arrived",
        "da den",
        "dang cho",
        "dang cho kham",
        "cho kham",
    }


def _build_patient_display_from_queue(request, selected_date, session_scope):
    """Read waiting-room rows directly from queue tokens for the selected doctor/date."""
    doctor_id = request.session.get("doctor_id")
    selected_date_iso = selected_date.isoformat()

    queue_lookup = _load_queue_lookup_for_date(selected_date_iso, doctor_id)
    if not isinstance(queue_lookup, dict) or not queue_lookup:
        return []

    appointments = _load_appointments_from_appointment_new(selected_date_iso, doctor_id)
    appointment_map = {}
    for apt in appointments:
        if not isinstance(apt, dict):
            continue
        apt_id = str(apt.get("id") or apt.get("appointmentID") or "").strip()
        if apt_id:
            appointment_map[apt_id] = apt

    rows = []
    for apt_id, entry in queue_lookup.items():
        appointment_id = str(apt_id or "").strip()
        if not appointment_id or not isinstance(entry, dict):
            continue

        token = entry.get("token")
        if not isinstance(token, dict):
            token = {}

        token_status = (
            token.get("status")
            or token.get("queueStatus")
            or token.get("state")
            or token.get("appointmentStatus")
        )
        token_waiting = _is_queue_waiting_status(token_status)

        apt = appointment_map.get(appointment_id, {})
        apt_waiting = _is_patient_display_arrived(apt) if isinstance(apt, dict) else False

        # Queue is the primary source for patient display.
        # However, many datasets have inconsistent token.status values (or missing status).
        # Keep row when token is waiting/arrived OR appointment status confirms arrived.
        # If token.status is empty, do not drop the row.
        if not token_waiting and not apt_waiting and str(token_status or "").strip():
            continue

        time_value = str(
            apt.get("time")
            or token.get("appointmentTime")
            or token.get("time")
            or ""
        ).strip()
        session_value = (
            apt.get("session")
            or apt.get("appointmentSession")
            or apt.get("sessionID")
            or token.get("session")
            or token.get("appointmentSession")
        )
        session_key, session_label, _ = _normalize_session(session_value, time_value)

        # Only enforce session filter when session can be determined reliably.
        # If session is unknown/other, keep the row so waiting patients are still visible.
        if session_scope != "all" and session_key in {"morning", "afternoon"} and session_key != session_scope:
            continue

        queue_number_raw = token.get("queueNumber") or token.get("position") or token.get("number")
        try:
            queue_number = int(queue_number_raw)
        except Exception:
            queue_number = 10**9

        display_queue_number = ""
        if queue_number != 10**9:
            display_queue_number = str(queue_number)
        elif queue_number_raw not in (None, ""):
            display_queue_number = str(queue_number_raw)

        priority_level_raw = token.get("priorityLevel") or 0
        try:
            priority_level = int(priority_level_raw)
        except Exception:
            priority_level = 0

        name = (
            token.get("patientName")
            or token.get("name")
            or token.get("fullName")
            or apt.get("name")
            or "Bệnh nhân chưa rõ tên"
        )

        rows.append({
            "appointment_id": appointment_id,
            "name": name,
            "queue_number": display_queue_number,
            "time_display": time_value or session_label,
            "session_key": session_key,
            "session_label": session_label,
            "status_key": "waiting",
            "status": "Đã đến",
            "isPriority": bool(priority_level > 50),
            "_queue_number": queue_number,
            "_priority_level": priority_level,
        })

    rows.sort(key=lambda item: (-item.get("_priority_level", 0), item.get("_queue_number", 10**9)))

    cleaned = []
    seen = set()
    for row in rows:
        apt_id = str(row.get("appointment_id") or "").strip()
        if not apt_id or apt_id in seen:
            continue
        seen.add(apt_id)
        row.pop("_queue_number", None)
        row.pop("_priority_level", None)
        cleaned.append(row)
        if len(cleaned) >= 15:
            break

    return cleaned


def patient_display_poll_view(request):
    """JSON endpoint for patient waiting room — returns only arrived (waiting) patients."""
    if not request.session.get('doctor_id'):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    selected_date = _parse_selected_date(request.GET.get('date'))
    session_scope = _get_patient_display_session_scope(selected_date)
    arrived = _build_patient_display_from_queue(request, selected_date, session_scope)

    snapshot_key = hashlib.md5(
        '|'.join(
            f"{a.get('appointment_id')}:{a.get('queue_number')}:{a.get('status_key')}:{a.get('isPriority')}:{a.get('name')}:{a.get('time_display')}"
            for a in arrived
        ).encode()
    ).hexdigest()

    client_key = (request.GET.get('snapshot_key') or '').strip()
    if client_key and client_key == snapshot_key:
        return JsonResponse({'changed': False, 'snapshot_key': snapshot_key})

    return JsonResponse({
        'changed': True,
        'snapshot_key': snapshot_key,
        'appointments': [
            {
                'appointment_id': a.get('appointment_id', ''),
                'name': a.get('name', ''),
                'queue_number': a.get('queue_number', ''),
                'time_display': a.get('time_display', ''),
                'session_label': a.get('session_label', ''),
                'status_key': a.get('status_key', ''),
                'status': a.get('status', ''),
                'isPriority': a.get('isPriority', False),
            }
            for a in arrived
        ],
    })


def patient_display_view(request):
    if request.session.get('admin_portal_user_id'):
        return redirect('admin_portal_dashboard')

    if not request.session.get('doctor_id'):
        return redirect('login')

    selected_date = _parse_selected_date(request.GET.get("date"))
    context = _build_dashboard_context(request, selected_date)
    session_scope = _get_patient_display_session_scope(selected_date)
    arrived_appointments = _build_patient_display_from_queue(request, selected_date, session_scope)

    initial_snapshot_key = hashlib.md5(
        '|'.join(
            f"{a.get('appointment_id')}:{a.get('queue_number')}:{a.get('status_key')}:{a.get('isPriority')}:{a.get('name')}:{a.get('time_display')}"
            for a in arrived_appointments
        ).encode()
    ).hexdigest()

    context.update({
        "all_today_appointments": arrived_appointments,
        "serving_appointment": arrived_appointments[0] if arrived_appointments else None,
        "next_up_appointments": arrived_appointments[1:7],
        "initial_snapshot_key": initial_snapshot_key,
        "patient_display_session_scope": session_scope,
    })

    return render(request, "appointments/patient_display.html", context)



def dashboard_view(request):
    if request.session.get('admin_portal_user_id'):
        return redirect('admin_portal_dashboard')

    if not request.session.get('doctor_id'):
        return redirect('login')

    return _render_dashboard_page(request)

    # ===== GET DATE =====
    selected_date_str = request.GET.get('date')

    if selected_date_str:
        try:
            selected_date = date.fromisoformat(selected_date_str)
        except:
            try:
                selected_date = datetime.strptime(selected_date_str, "%d/%m/%Y").date()
            except:
                selected_date = date.today()
    else:
        selected_date = date.today()

    # ===== DOCTOR SESSION =====
    doctor_id = request.session.get("doctor_id")

    # ===== LOAD APPOINTMENTS =====
    all_appointments = _load_appointments_from_appointment_new(
        selected_date.isoformat(),
        doctor_id,
    )

    # ===== LOAD PATIENTS =====
    patient_ids = list({
        apt.get("patientID")
        for apt in all_appointments
        if apt.get("patientID")
    })

    patients_map = get_patients_by_ids(patient_ids)

    print("Patient IDs:", patient_ids)
    print("Patients map:", patients_map)

    # ===== MERGE PATIENT DATA =====
    for apt in all_appointments:

        patient = patients_map.get(apt.get("patientID", ""))

        if patient:
            apt["name"] = patient.get("name", "")
            apt["phone"] = patient.get("phone", "")
            apt["gender"] = normalize_gender(patient.get("gender", ""))
            birthdate = patient.get("birthdate", "")

            print("Birthdate raw:", birthdate)

            apt["birthdate"] = birthdate
            apt["age"] = calculate_age(birthdate)

            print("Age calculated:", apt["age"])
        
        # IMPORTANT: Set apt["id"] to appointment ID (for examine_view), not patient ID
        apt["id"] = apt.get("id", apt.get("appointmentID", ""))

        # ===== MAP STATUS =====
        status = apt.get("status", "").lower()

        if status == "scheduled":
            apt["status"] = "Chưa đến"
        elif status == "đang chờ khám":
            apt["status"] = "Đang chờ khám"
        elif status in {"đã khám", "completed", "complete"}:
            apt["status"] = "Đã khám"
        elif status == "cancelled":
            apt["status"] = "Đã hủy"

    # ===== PRIORITY SESSION =====
    priorities = request.session.get("priorities", {})

    morning_appointments = []
    afternoon_appointments = []

    for apt in all_appointments:

        patient_id = apt.get("patientID", "")

        if patient_id in priorities:
            priority_info = priorities[patient_id]
            apt["isPriority"] = priority_info.get("status", False)
            apt["priorityReason"] = priority_info.get("reason", "")
        else:
            apt["isPriority"] = False
            apt["priorityReason"] = ""

        # ===== KHÔNG DÙNG TIME → CHO VÀO MORNING =====
        morning_appointments.append(apt)

    # ===== SORT APPOINTMENTS =====
    def sort_appointments(appointments):

        def sort_key(apt):

            is_priority = 0 if apt.get("isPriority") else 1

            status = apt.get("status", "")

            if status == "Đang chờ khám":
                status_priority = 0
            elif status == "Chưa đến":
                status_priority = 1
            elif status == "Đã khám":
                status_priority = 2
            else:
                status_priority = 3

            return (is_priority, status_priority)

        return sorted(appointments, key=sort_key)

    morning_appointments = sort_appointments(morning_appointments)
    afternoon_appointments = sort_appointments(afternoon_appointments)

    # ===== SEARCH =====
    search_query = request.GET.get("search", "").strip().lower()

    if search_query:

        morning_appointments = [
            p for p in morning_appointments
            if search_query in p.get("name", "").lower()
            or search_query in p.get("phone", "").lower()
        ]

        afternoon_appointments = [
            p for p in afternoon_appointments
            if search_query in p.get("name", "").lower()
            or search_query in p.get("phone", "").lower()
        ]

    # ===== WAITING LIST =====
    waiting_list = sorted(
        [
            apt for apt in all_appointments
            if apt.get("status") == "Đang chờ khám"
        ],
        key=lambda x: x.get("name", "")
    )

    print("Doctor ID:", doctor_id)
    print("Selected date:", selected_date.isoformat())
    print("Appointments found:", len(all_appointments))

    # ===== CHECK TODAY =====
    is_today = selected_date == date.today()

    return render(
        request,
        "appointments/dashboard.html",
        {
            "morning_appointments": morning_appointments,
            "afternoon_appointments": afternoon_appointments,
            "all_today_appointments": morning_appointments + afternoon_appointments,
            "waiting_list": [p.get("name", "") for p in waiting_list],
            "today": selected_date,
            "selected_date": selected_date_str or selected_date.isoformat(),
            "search_query": search_query,
            "is_today": is_today,
        }
    )

def history_view(request):
    from services.RTDB_utils import get_appointments_by_date_range_for_doctor

    def _parse_history_date(raw_value):
        raw_value = (raw_value or "").strip()
        if not raw_value:
            return None
        try:
            return date.fromisoformat(raw_value)
        except Exception:
            return None

    # Backward compatibility: keep supporting ?date=YYYY-MM-DD
    legacy_date = _parse_history_date(request.GET.get("date"))
    selected_start_date = _parse_history_date(request.GET.get("date_from"))
    selected_end_date = _parse_history_date(request.GET.get("date_to"))

    if not selected_start_date and legacy_date:
        selected_start_date = legacy_date
    if not selected_end_date and legacy_date:
        selected_end_date = legacy_date

    # Default: yesterday when user has not selected any date.
    fallback_date = date.today() - timedelta(days=1)
    if not selected_start_date and not selected_end_date:
        selected_start_date = fallback_date
        selected_end_date = fallback_date
    elif selected_start_date and not selected_end_date:
        selected_end_date = selected_start_date
    elif selected_end_date and not selected_start_date:
        selected_start_date = selected_end_date

    if selected_start_date > selected_end_date:
        selected_start_date, selected_end_date = selected_end_date, selected_start_date

    search_query = (request.GET.get("search") or "").strip()
    search_terms = _normalize_search_text(search_query)

    # Get logged in doctor ID from session
    doctor_id = request.session.get('doctor_id')

    # Single-pass range query to reduce repeated RTDB reads.
    history_appointments = get_appointments_by_date_range_for_doctor(
        selected_start_date.isoformat(),
        selected_end_date.isoformat(),
        doctor_id,
    )

    # Lịch sử khám chỉ hiển thị các ca đã khám thành công.
    # Loại trừ scheduled / waiting / cancelled / no_show.
    _completed_status_keys = {"đã khám", "da kham", "completed", "complete"}
    history_appointments = [
        apt for apt in history_appointments
        if str(apt.get("status", "")).strip().lower() in _completed_status_keys
    ]

    if search_terms:
        filtered_history_appointments = []
        for apt in history_appointments:
            patient = apt.get("patient_info", {})
            searchable_text = " ".join([
                str(apt.get("date") or ""),
                str(apt.get("time") or ""),
                str(apt.get("status") or ""),
                str(apt.get("symptoms") or ""),
                str(apt.get("diagnosis") or ""),
                str(apt.get("advice") or ""),
                str(patient.get("name") or ""),
                str(patient.get("phone") or ""),
                str(patient.get("gender") or ""),
            ])
            if search_terms in _normalize_search_text(searchable_text):
                filtered_history_appointments.append(apt)
        history_appointments = filtered_history_appointments

    for apt in history_appointments:
        apt_date_str = (apt.get("date") or "").strip()
        try:
            apt_date = date.fromisoformat(apt_date_str) if apt_date_str else selected_end_date
        except Exception:
            apt_date = selected_end_date

        patient = apt.get("patient_info", {})
        apt["birthdate"] = patient.get("birthdate", "")
        apt["age"] = calculate_age(patient.get("birthdate", ""), apt_date)
        apt["name"] = patient.get("name", "")
        apt["gender"] = normalize_gender(patient.get("gender", ""))
        status_key, status_label = normalize_status(apt.get("status", ""))
        apt["status_key"] = status_key
        apt["status"] = status_label

    history_appointments.sort(
        key=lambda x: ((x.get("date") or ""), (x.get("time") or "")),
        reverse=True,
    )

    history_total_count = len(history_appointments)
    page_size = 10
    paginator = Paginator(history_appointments, page_size)
    page_number = request.GET.get("page") or 1
    try:
        history_page = paginator.page(page_number)
    except PageNotAnInteger:
        history_page = paginator.page(1)
    except EmptyPage:
        history_page = paginator.page(paginator.num_pages)

    # Tất cả lịch hẹn còn lại đều là đã khám sau khi đã filter.
    completed_count = history_total_count
    unique_patient_count = len({
        (apt.get("patientID") or apt.get("patient_id") or "").strip()
        for apt in history_appointments
        if (apt.get("patientID") or apt.get("patient_id") or "").strip()
    })
    range_days = (selected_end_date - selected_start_date).days + 1

    return render(request, "appointments/history_new.html", {
        "selected_date": selected_end_date,
        "selected_start_date": selected_start_date,
        "selected_end_date": selected_end_date,
        "search_query": search_query,
        "history_appointments": history_page.object_list,
        "history_total_count": history_total_count,
        "history_page_obj": history_page,
        "completed_count": completed_count,
        "unique_patient_count": unique_patient_count,
        "range_days": range_days,
    })


def examine_view(request, appointment_id):
    from services.RTDB_utils import (
        get_appointment_with_patient_info,
        get_patient_medical_records_for_doctor,
        save_examination,
        update_appointment,
    )

    doctor_id = (request.session.get("doctor_id") or "").strip()
    if not doctor_id:
        return redirect("login")

    appointment = get_appointment_with_patient_info(appointment_id)
    if not appointment:
        return redirect("dashboard")

    appointment_doctor_id = str(appointment.get("doctorID") or "").strip()

    if appointment_doctor_id and appointment_doctor_id != doctor_id:
        messages.error(request, "Bạn không có quyền xem hồ sơ bệnh án của bệnh nhân này.")
        return redirect("dashboard")

    if not appointment_doctor_id:
        # Claim unassigned appointment to establish doctor-patient linkage.
        update_appointment(appointment_id, doctorID=doctor_id)
        appointment["doctorID"] = doctor_id

    patient_info = appointment.get("patient_info", {})
    patient_id = str(patient_info.get("id") or appointment.get("patientID") or "").strip()

    # Access has already been verified above (appointment_doctor_id == doctor_id).
    # Medical records are loaded asynchronously via AJAX (examine_medical_records_ajax_view)
    # so the page renders immediately without waiting for this Firebase call.

    if not patient_id:
        messages.error(request, "Không tìm thấy thông tin bệnh nhân của lịch khám.")
        return redirect("dashboard")

    patient = {
        "id": patient_info.get("id", ""),
        "name": patient_info.get("name", "N/A"),
        "age": calculate_age(patient_info.get("birthdate", "")),
        "gender": normalize_gender(patient_info.get("gender", "")),
        "birthdate": patient_info.get("birthdate", ""),
        "phone": patient_info.get("phone", ""),
        "address": patient_info.get("address", ""),
        "medical_history": patient_info.get("medical_history", ""),
        "appointment_id": appointment_id,
        "appointment_time": appointment.get("time", ""),
        "appointment_date": appointment.get("date", ""),
        "current_symptoms": appointment.get("symptoms", ""),
        "current_diagnosis": appointment.get("diagnosis", ""),
        "current_advice": appointment.get("advice", "")
    }

    if request.method == "POST":
        # Lấy dữ liệu từ form
        symptoms = request.POST.get("symptom", "").strip()
        diagnosis = request.POST.get("diagnosis", "").strip()
        advice = request.POST.get("advice", "").strip()
        
        # Vital signs
        vital_signs = {
            "blood_pressure": request.POST.get("blood_pressure", "").strip(),
            "pulse": request.POST.get("pulse", "").strip(),
            "temperature": request.POST.get("temperature", "").strip(),
            "weight": request.POST.get("weight", "").strip(),
        }
        
        # Prescription - xử lý danh sách thuốc
        med_names = request.POST.getlist("med_name[]")
        med_doses = request.POST.getlist("med_dose[]")
        med_qtys = request.POST.getlist("med_qty[]")
        med_notes = request.POST.getlist("med_note[]")
        
        prescription = []
        for i in range(len(med_names)):
            if med_names[i].strip():  # Chỉ thêm nếu có tên thuốc
                prescription.append({
                    "name": med_names[i].strip(),
                    "dose": med_doses[i].strip() if i < len(med_doses) else "",
                    "quantity": med_qtys[i].strip() if i < len(med_qtys) else "",
                    "note": med_notes[i].strip() if i < len(med_notes) else ""
                })
        
        # Gọi hàm lưu khám với đầy đủ dữ liệu
        save_examination(
            appointment_id, 
            symptoms=symptoms, 
            diagnosis=diagnosis, 
            advice=advice,
            vital_signs=vital_signs,
            prescription=prescription
        )

        # Invalidate dashboard cache so the doctor's dashboard reflects completion immediately.
        try:
            invalidate_dashboard_cache(
                doctor_id=doctor_id,
                selected_date_iso=str(appointment.get('appointmentDate') or appointment.get('date') or '').strip(),
            )
        except Exception as inv_err:
            print(f"⚠️ examine cache invalidation failed: {inv_err}")

        # Notify next patients in queue that they're getting closer.
        try:
            _notify_date = str(appointment.get('appointmentDate') or appointment.get('date') or '').strip()
            # Normalize to ISO if needed
            if '/' in _notify_date:
                try:
                    from datetime import datetime as _dt
                    for _fmt in ("%d/%m/%Y", "%Y/%m/%d"):
                        try:
                            _notify_date = _dt.strptime(_notify_date, _fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass
            print(f"[EXAMINE] Calling notify_queue_advance(doctor_id={doctor_id}, date={_notify_date})")
            notify_queue_advance(
                doctor_id=doctor_id,
                selected_date_iso=_notify_date,
            )
        except Exception as notif_err:
            print(f"⚠️ examine queue notification failed: {notif_err}")

        # Examination finished: remove generated call/reminder audio for this appointment.
        _cleanup_tts_files_for_appointment(appointment_id)
        
        return redirect("dashboard")

    now = timezone.localtime()
    return render(
        request,
        "appointments/examine_views.html",
        {
            "patient": patient,
            "current_time": now.strftime("%H:%M"),
            "current_date": now.strftime("%d/%m/%Y"),
        },
    )


def examine_medical_records_ajax_view(request, appointment_id):
    """AJAX endpoint: returns medical records summary for the given appointment.

    Instead of streaming the full list of previous records (which can be long
    and pushes the examination form below the fold), we return only:
      - ``count``: number of previous records the doctor is allowed to see
      - ``latest_date`` / ``latest_time``: most recent exam timestamp (display)

    The frontend renders a single button that opens the dedicated patient
    record page when count > 0.
    """
    from django.http import JsonResponse
    from services.RTDB_utils import (
        get_appointment_by_id,
        get_patient_medical_records_for_doctor,
    )

    doctor_id = (request.session.get("doctor_id") or "").strip()
    if not doctor_id:
        return JsonResponse({"error": "unauthenticated"}, status=401)

    # Appointment will almost always be a cache hit here (15 s TTL set during examine_view render)
    apt = get_appointment_by_id(appointment_id)
    if not apt:
        return JsonResponse({"count": 0})

    appointment_doctor_id = str(apt.get("doctorID") or "").strip()
    if appointment_doctor_id and appointment_doctor_id != doctor_id:
        return JsonResponse({"error": "forbidden"}, status=403)

    patient_id = str(apt.get("patientID") or "").strip()
    records = get_patient_medical_records_for_doctor(doctor_id, patient_id, trust_access=True)

    if not records:
        return JsonResponse({"count": 0})

    # Records are sorted descending by date/time in get_patient_medical_records_for_doctor;
    # take the first as the "latest" entry to show.
    latest = records[0] if records else {}
    return JsonResponse({
        "count": len(records),
        "latest_date": latest.get("examDate", ""),
        "latest_time": latest.get("examTime", ""),
    })


def patient_record_view(request, appointment_id):
    from services.RTDB_utils import get_appointment_with_patient_info

    doctor_id = (request.session.get("doctor_id") or "").strip()
    if not doctor_id:
        messages.error(request, "Bạn cần đăng nhập với vai trò bác sĩ để xem hồ sơ.")
        return redirect("login")

    appointment = get_appointment_with_patient_info(appointment_id)
    if not appointment:
        messages.error(request, "Không tìm thấy lịch khám tương ứng.")
        return redirect("dashboard")

    patient_info = appointment.get("patient_info", {})
    patient_id = str(patient_info.get("id") or appointment.get("patientID") or "").strip()

    # Kiểm tra quyền: get_patient_medical_records_for_doctor đã tự filter
    # theo doctorID/specialtyID trên từng record. Nếu trả về rỗng = không có quyền.
    medical_records = get_patient_medical_records_for_doctor(doctor_id, patient_id)
    if not medical_records:
        messages.error(
            request,
            "Không đủ điều kiện xem hồ sơ: bác sĩ chưa có liên hệ khám trực tiếp hoặc cùng khoa với bệnh nhân này.",
        )
        return redirect("dashboard")

    patient = {
        "id": patient_info.get("id", ""),
        "name": patient_info.get("name", "N/A"),
        "age": calculate_age(patient_info.get("birthdate", "")),
        "gender": normalize_gender(patient_info.get("gender", "")),
        "birthdate": patient_info.get("birthdate", ""),
        "phone": patient_info.get("phone", ""),
        "address": patient_info.get("address", ""),
        "medical_history": patient_info.get("medical_history", ""),
    }

    status_key, status_label = normalize_status(appointment.get("status", ""))

    current_session = {
        "appointment_id": appointment_id,
        "date": appointment.get("date", ""),
        "time": appointment.get("time", ""),
        "status_key": status_key,
        "status": status_label,
        "reason": appointment.get("summary", "") or appointment.get("reason", ""),
        "symptoms": appointment.get("symptoms", ""),
        "diagnosis": appointment.get("diagnosis", ""),
        "advice": appointment.get("advice", ""),
    }

    return render(
        request,
        "appointments/patient_record.html",
        {
            "patient": patient,
            "current_session": current_session,
            "medical_records": medical_records,
        },
    )


def patient_record_search_view(request):
    doctor_id = (request.session.get("doctor_id") or "").strip()
    if not doctor_id:
        messages.error(request, "Bạn cần đăng nhập với vai trò bác sĩ để tra cứu hồ sơ.")
        return redirect("login")

    query = (request.GET.get("q") or "").strip().lower()

    # Lấy specialtyID của bác sĩ đang đăng nhập
    doctor = get_doctor_by_id(doctor_id) or {}
    doctor_specialty = str(doctor.get("specialtyID") or "").strip().strip('"\'')

    # ---- Cached eligible-record list keyed per doctor ----
    # Lần đầu vào trang: quét toàn bộ medicalRecords (chậm).
    # Các lần phân trang / search trong cùng phiên: lấy từ cache (~ms).
    cache_key = f"prs_records:{doctor_id}:{doctor_specialty}"
    all_records = cache.get(cache_key)
    cache_hit = all_records is not None

    if not cache_hit:
        all_medical_records = db.child("medicalRecords").get() or {}
        if not isinstance(all_medical_records, dict):
            all_medical_records = {}

        # Lọc: chỉ lấy bệnh nhân có ít nhất 1 record mà bác sĩ này có quyền xem
        eligible_patients = {}  # {patientID: latest_record}
        for pid, patient_records in all_medical_records.items():
            if not isinstance(patient_records, dict):
                continue

            latest_record = None
            for entry_id, record in patient_records.items():
                if not isinstance(record, dict):
                    continue

                record_doctor_id = str(record.get("doctorID") or "").strip()
                record_specialty_id = str(record.get("specialtyID") or "").strip().strip('"\'')

                # Kiểm tra quyền: doctorID match HOẶC specialtyID match
                is_own = record_doctor_id == doctor_id
                is_same_spec = (doctor_specialty and record_specialty_id and record_specialty_id == doctor_specialty)

                if not is_own and not is_same_spec:
                    continue

                # Giữ record mới nhất
                if latest_record is None:
                    latest_record = record
                else:
                    if str(record.get("examDate") or "") >= str(latest_record.get("examDate") or ""):
                        latest_record = record

            if latest_record:
                eligible_patients[pid] = latest_record

        patient_ids = list(eligible_patients.keys())
        patients_map = get_patients_by_ids(patient_ids)

        all_records = []
        for pid, latest_record in eligible_patients.items():
            patient = patients_map.get(pid, {})

            name = (patient.get("name") or "Bệnh nhân chưa rõ tên").strip()
            phone = (patient.get("phone") or "").strip()
            birthdate = _extract_birthdate(patient)

            appointment_id = str(latest_record.get("appointmentID") or "").strip()
            searchable = " ".join([
                name.lower(),
                phone.lower(),
                str(pid).lower(),
                appointment_id.lower(),
            ])

            all_records.append({
                "patient_id": pid,
                "name": name,
                "phone": phone,
                "gender": normalize_gender(patient.get("gender", "")),
                "age": calculate_age(birthdate),
                "birthdate": birthdate,
                "last_date": latest_record.get("examDate", ""),
                "last_time": latest_record.get("examTime", ""),
                "status_key": "completed",
                "status": "Đã khám",
                "appointment_id": appointment_id,
                "can_open_record": bool(appointment_id),
                # Pre-computed lowercase blob for search filtering on subsequent paginations
                "_searchable": searchable,
            })

        # Sắp xếp theo ngày khám gần nhất (mới nhất lên đầu) — sort 1 lần, cache giữ thứ tự
        all_records.sort(key=lambda r: str(r.get("last_date") or ""), reverse=True)

        # Cache 60 giây (đủ cho người dùng phân trang nhiều trang liên tiếp).
        # Cache sẽ invalidate khi thêm record mới (xem save_examination / add_medical_record).
        cache.set(cache_key, all_records, 60)
        try:
            from services.RTDB_utils import _register_patient_record_search_cache_key
            _register_patient_record_search_cache_key(cache_key)
        except Exception:
            pass

    # Filter theo query (rẻ vì làm trên list trong RAM)
    if query:
        records = [r for r in all_records if query in r.get("_searchable", "")]
    else:
        records = all_records

    total_related_patients = len(all_records)

    # Phân trang: 10 hồ sơ mỗi trang
    paginator = Paginator(records, 10)
    page_number = request.GET.get("page", 1)
    try:
        page_obj = paginator.page(page_number)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    return render(
        request,
        "appointments/patient_record_search.html",
        {
            "records": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "is_paginated": page_obj.has_other_pages(),
            "query": request.GET.get("q", ""),
            "total_related_patients": total_related_patients,
            "filtered_count": len(records),
        },
    )


def statistics_view(request):
    import json
    from collections import OrderedDict
    from services.RTDB_utils import get_all_appointments

    # Get logged in doctor ID from session
    doctor_id = request.session.get('doctor_id')

    # Get period parameter from request (default: "month")
    period = request.GET.get('period', 'month').lower()
    date_from_raw = (request.GET.get('date_from', '') or '').strip()
    date_to_raw = (request.GET.get('date_to', '') or '').strip()

    # Parse custom date range
    date_from = None
    date_to = None
    if date_from_raw:
        try:
            date_from = date.fromisoformat(date_from_raw)
        except Exception:
            date_from = None
    if date_to_raw:
        try:
            date_to = date.fromisoformat(date_to_raw)
        except Exception:
            date_to = None

    # If both dates given → switch to "range" mode
    if date_from and date_to:
        period = 'range'
        if date_from > date_to:
            date_from, date_to = date_to, date_from

    doctor_id_str = str(doctor_id or '').strip()
    doctor_id_variants = {doctor_id_str} if doctor_id_str else set()
    if doctor_id_str:
        if doctor_id_str.startswith('doc_'):
            doctor_id_variants.add(doctor_id_str[4:])
        else:
            doctor_id_variants.add(f'doc_{doctor_id_str}')

    # Single full read of appointment_new (cached 30 s in get_all_appointments).
    # The cached snapshot makes repeated period switches ~ms instead of seconds.
    all_appointments = get_all_appointments()

    def normalize_apt_date(apt):
        raw = str(apt.get('date') or apt.get('appointmentDate') or '').strip()
        if not raw:
            return None
        if 'T' in raw:
            raw = raw.split('T', 1)[0]
        try:
            return date.fromisoformat(raw)
        except Exception:
            try:
                return datetime.strptime(raw, "%d/%m/%Y").date()
            except Exception:
                return None

    def doctor_matches(apt):
        if not doctor_id_variants:
            return True
        return str(apt.get('doctorID') or '').strip() in doctor_id_variants

    def build_period_buckets():
        today_value = date.today()
        buckets = OrderedDict()

        if period == 'range' and date_from and date_to:
            # Custom range — bucket theo ngày (nếu khoảng <= 31 ngày) hoặc theo tuần
            span_days = (date_to - date_from).days + 1
            if span_days <= 31:
                # Bucket theo ngày
                day_value = date_from
                while day_value <= date_to:
                    key = day_value.isoformat()
                    buckets[key] = {
                        'label': day_value.strftime('%d/%m/%Y'),
                        'date': day_value,
                    }
                    day_value += timedelta(days=1)
                period_label = f"từ {date_from.strftime('%d/%m/%Y')} đến {date_to.strftime('%d/%m/%Y')}"
                return buckets, period_label, lambda d: d.isoformat()
            elif span_days <= 365:
                # Bucket theo tuần
                week_start = date_from - timedelta(days=date_from.weekday())
                while week_start <= date_to:
                    week_end = week_start + timedelta(days=6)
                    key = week_start.isoformat()
                    buckets[key] = {
                        'label': f"{week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')}",
                        'week': f"{week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')}",
                    }
                    week_start += timedelta(weeks=1)
                period_label = f"từ {date_from.strftime('%d/%m/%Y')} đến {date_to.strftime('%d/%m/%Y')} (theo tuần)"
                return buckets, period_label, lambda d: (d - timedelta(days=d.weekday())).isoformat()
            else:
                # Bucket theo tháng
                year, month = date_from.year, date_from.month
                end_year, end_month = date_to.year, date_to.month
                while (year, month) <= (end_year, end_month):
                    key = f"{year:04d}-{month:02d}"
                    buckets[key] = {
                        'label': key,
                        'month': key,
                    }
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1
                period_label = f"từ {date_from.strftime('%d/%m/%Y')} đến {date_to.strftime('%d/%m/%Y')} (theo tháng)"
                return buckets, period_label, lambda d: d.strftime('%Y-%m')

        if period == 'day':
            for offset in range(29, -1, -1):
                day_value = today_value - timedelta(days=offset)
                key = day_value.isoformat()
                buckets[key] = {
                    'label': day_value.strftime('%d/%m/%Y'),
                    'date': day_value,
                }
            return buckets, "theo ngày (30 ngày gần nhất)", lambda d: d.isoformat()

        if period == 'week':
            current_week_start = today_value - timedelta(days=today_value.weekday())
            for offset in range(11, -1, -1):
                week_start = current_week_start - timedelta(weeks=offset)
                week_end = week_start + timedelta(days=6)
                key = week_start.isoformat()
                buckets[key] = {
                    'label': f"{week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')}",
                    'week': f"{week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')}",
                }
            return buckets, "theo tuần (12 tuần gần nhất)", lambda d: (d - timedelta(days=d.weekday())).isoformat()

        if period == 'year':
            for offset in range(4, -1, -1):
                year_value = today_value.year - offset
                key = str(year_value)
                buckets[key] = {
                    'label': key,
                    'year': key,
                }
            return buckets, "theo năm (5 năm gần nhất)", lambda d: str(d.year)

        for offset in range(11, -1, -1):
            month_index = today_value.month - offset
            year_value = today_value.year
            while month_index <= 0:
                month_index += 12
                year_value -= 1
            key = f"{year_value:04d}-{month_index:02d}"
            buckets[key] = {
                'label': key,
                'month': key,
            }
        return buckets, "theo tháng (12 tháng gần nhất)", lambda d: d.strftime('%Y-%m')

    buckets, period_name, bucket_key_for_date = build_period_buckets()

    for bucket in buckets.values():
        bucket.update({
            'count': 0,
            'booked_count': 0,
            'arrived_count': 0,
            'cancelled_count': 0,
            'no_show_count': 0,
        })

    for apt in all_appointments:
        if not doctor_matches(apt):
            continue

        apt_date = normalize_apt_date(apt)
        if not apt_date:
            continue

        # Filter by custom range
        if period == 'range' and date_from and date_to:
            if apt_date < date_from or apt_date > date_to:
                continue

        bucket_key = bucket_key_for_date(apt_date)
        if bucket_key not in buckets:
            continue

        status_key, _ = normalize_status(apt.get('status', ''))
        bucket = buckets[bucket_key]
        if status_key == 'scheduled':
            bucket['booked_count'] += 1
        elif status_key in ('waiting', 'completed'):
            bucket['arrived_count'] += 1
        elif status_key == 'cancelled':
            bucket['cancelled_count'] += 1
        elif status_key == 'no_show':
            bucket['no_show_count'] += 1

        bucket['count'] = (
            bucket['booked_count']
            + bucket['arrived_count']
            + bucket['cancelled_count']
            + bucket['no_show_count']
        )

    stats = list(buckets.values())
    labels = [s['label'] for s in stats]
    booked_chart = [s['booked_count'] for s in stats]
    arrived_chart = [s['arrived_count'] for s in stats]
    cancelled_chart = [s['cancelled_count'] for s in stats]
    no_show_chart = [s['no_show_count'] for s in stats]

    totals = {
        'booked': sum(booked_chart),
        'arrived': sum(arrived_chart),
        'cancelled': sum(cancelled_chart),
        'no_show': sum(no_show_chart),
    }

    return render(request, "appointments/statistics.html", {
        "stats": stats,
        "labels": json.dumps(labels),
        "booked_data": json.dumps(booked_chart),
        "arrived_data": json.dumps(arrived_chart),
        "cancelled_data": json.dumps(cancelled_chart),
        "no_show_data": json.dumps(no_show_chart),
        "totals": totals,
        "period": period,
        "period_name": period_name,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "today": date.today()
    })


@csrf_exempt
def scan_view(request):
    """QR code scan endpoint.

    GET  → render the scan page (doctor uses this to scan patient QR codes).
    POST → mark appointment as arrived (status='Đã đến', records arrivalTime).

    The arrivalTime timestamp is used for FCFS ordering within the waiting queue.
    Duplicate scans are idempotent — the original arrivalTime is preserved.
    """
    if not request.session.get("doctor_id"):
        if request.method == "GET":
            return redirect("login")
        return JsonResponse({"success": False, "message": "Unauthorized"}, status=401)

    if request.method == "GET":
        return render(request, "appointments/scan.html", {})

    if request.method == "POST":
        try:
            import json as _json
            data = _json.loads(request.body)
            appointment_id = (data.get("appointment_id") or "").strip()
            if not appointment_id:
                return JsonResponse({"success": False, "message": "appointment_id is required"})

            updated = mark_appointment_arrived(appointment_id)
            if updated:
                # Invalidate dashboard cache so doctor's poll picks up the new arrival immediately.
                try:
                    invalidate_dashboard_cache(
                        doctor_id=str(updated.get('doctorID') or '').strip(),
                        selected_date_iso=str(updated.get('appointmentDate') or updated.get('date') or '').strip(),
                    )
                except Exception as inv_err:
                    print(f"⚠️ scan cache invalidation failed: {inv_err}")

                # Notify patients in queue about position changes after new check-in.
                try:
                    notify_queue_advance(
                        doctor_id=str(updated.get('doctorID') or '').strip(),
                        selected_date_iso=str(updated.get('appointmentDate') or updated.get('date') or '').strip(),
                    )
                except Exception as notif_err:
                    print(f"⚠️ scan queue notification failed: {notif_err}")

                # Pre-generate call audio right after scan to reduce delay on doctor click.
                try:
                    patient_id = str(updated.get('patientID') or '').strip()
                    patient = get_patient_by_id(patient_id) if patient_id else {}
                    patient_name = str((patient or {}).get('name') or '').strip()
                    if patient_name:
                        tts_data = _ensure_tts_files_for_appointment(appointment_id, patient_name, updated.get("queue_position", ""))
                        tts_audio_url = tts_data['call_url']
                        tts_remind_audio_url = tts_data['remind_url']
                    else:
                        tts_audio_url = ''
                        tts_remind_audio_url = ''
                except Exception as tts_err:
                    print(f"⚠️ scan pre-generate TTS failed: {tts_err}")
                    tts_audio_url = ''
                    tts_remind_audio_url = ''

                return JsonResponse({
                    "success": True,
                    "appointment": {
                        "id": appointment_id,
                        "status": updated.get("status", "Đã đến"),
                        "arrivalTime": updated.get("arrivalTime", ""),
                    },
                    "tts_audio_url": tts_audio_url,
                    "tts_remind_audio_url": tts_remind_audio_url,
                })
            else:
                return JsonResponse({"success": False, "message": "Failed to update appointment"})
        except Exception as e:
            return JsonResponse({"success": False, "message": str(e)})

    return JsonResponse({"success": False, "message": "Method not allowed"}, status=405)


@csrf_exempt
def update_priority_view(request):
    """Handle AJAX request to update patient priority status.

    Priority is now persisted in RTDB (under appointments/{id}/priority) instead
    of the Django session so it survives logout and is shared across devices.
    Priority is naturally per-appointment (and therefore per-session) because
    each appointment has its own unique ID.

    Expected POST data:
    - appointment_id: appointment ID (required)
    - is_priority: boolean (required)
    - priority_reason: text description/keywords (optional)
    - priority_tier: explicit tier override (low/medium/high/critical) (optional)
      If provided, skips keyword analysis and uses this tier directly.
    """
    if request.method != 'POST':
        return JsonResponse({"success": False, "message": "Invalid request method"})

    try:
        import json
        data = json.loads(request.body)
        appointment_id = data.get("appointment_id")
        is_priority = data.get("is_priority", False)
        priority_reason = data.get("priority_reason", "")
        priority_tier = data.get("priority_tier")  # Optional explicit tier

        if not appointment_id:
            return JsonResponse({"success": False, "message": "appointment_id is required"})

        success = set_appointment_priority(appointment_id, bool(is_priority), priority_reason, priority_tier)

        if success:
            # Invalidate dashboard cache so priority change shows up on next poll.
            try:
                from services.RTDB_utils import get_appointment_by_id
                apt = get_appointment_by_id(appointment_id) or {}
                invalidate_dashboard_cache(
                    doctor_id=str(apt.get('doctorID') or '').strip(),
                    selected_date_iso=str(apt.get('appointmentDate') or apt.get('date') or '').strip(),
                )
            except Exception as inv_err:
                print(f"⚠️ priority cache invalidation failed: {inv_err}")
            return JsonResponse({"success": True, "message": "Priority updated"})
        else:
            return JsonResponse({"success": False, "message": "Failed to update priority in database"})
    except Exception as e:
        print(f"Error updating priority: {e}")
        return JsonResponse({"success": False, "message": str(e)})


@csrf_exempt
def mark_no_show_view(request):
    """Mark an appointment as no_show (bệnh nhân không đến).
    
    POST JSON: { appointment_id, reason }
    """
    if request.method != 'POST':
        return JsonResponse({"success": False, "message": "Invalid method"}, status=405)

    doctor_id = (request.session.get("doctor_id") or "").strip()
    if not doctor_id:
        return JsonResponse({"success": False, "message": "Unauthorized"}, status=401)

    try:
        from services.RTDB_utils import update_appointment, get_appointment_by_id

        data = json.loads(request.body)
        appointment_id = (data.get("appointment_id") or "").strip()
        reason = (data.get("reason") or "manual").strip()

        if not appointment_id:
            return JsonResponse({"success": False, "message": "appointment_id is required"})

        apt = get_appointment_by_id(appointment_id)
        if not apt:
            return JsonResponse({"success": False, "message": "Appointment not found"})

        # Only allow marking scheduled or waiting appointments as no_show
        current_status = str(apt.get("status") or "").strip().lower()
        if current_status in ("completed", "no_show", "cancelled"):
            return JsonResponse({"success": False, "message": f"Không thể đánh dấu: trạng thái hiện tại là {current_status}"})

        update_appointment(
            appointment_id,
            status="no_show",
            noShowReason=reason,
            noShowAt=datetime.now().isoformat(),
        )

        # Invalidate cache
        try:
            invalidate_dashboard_cache(
                doctor_id=str(apt.get('doctorID') or doctor_id).strip(),
                selected_date_iso=str(apt.get('appointmentDate') or apt.get('date') or '').strip(),
            )
        except Exception:
            pass

        return JsonResponse({"success": True, "message": "Đã đánh dấu không đến"})
    except Exception as e:
        print(f"⚠️ mark_no_show_view error: {e}")
        return JsonResponse({"success": False, "message": str(e)})


def priority_categories_view(request):
    """Return all priority categories for UI dropdown/display.
    
    GET /appointments/priority-categories/
    
    Returns JSON with PRIORITY_CATEGORIES, PRIORITY_CHOICES, PRIORITY_COLORS, PRIORITY_ICONS.
    """
    try:
        from appointments.priority_categories import (
            PRIORITY_CATEGORIES,
            PRIORITY_CHOICES,
            PRIORITY_COLORS,
            PRIORITY_ICONS,
        )
        
        return JsonResponse({
            "success": True,
            "categories": PRIORITY_CATEGORIES,
            "choices": PRIORITY_CHOICES,
            "colors": PRIORITY_COLORS,
            "icons": PRIORITY_ICONS,
        })
    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": f"Error loading priority categories: {e}"
        })


def referral_view(request, appointment_id):
    """Refer/transfer a patient to another doctor or specialty."""
    if request.session.get("admin_portal_user_id"):
        return redirect("admin_portal_dashboard")

    doctor_id = request.session.get("doctor_id")
    if not doctor_id:
        return redirect("login")

    from services.RTDB_utils import (
        get_appointment_by_id as _get_apt,
        get_patient_by_id as _get_patient,
        get_all_doctors as _get_doctors,
        get_all_specialties as _get_specialties,
        get_doctor_by_id as _get_doctor,
        create_referral_appointment,
    )

    appointment = _get_apt(appointment_id)
    if not appointment:
        messages.error(request, "Không tìm thấy lịch khám.")
        return redirect("dashboard")

    patient_id = appointment.get("patientID", "")
    patient = _get_patient(patient_id) if patient_id else {}
    patient = patient or {}

    source_doctor = _get_doctor(doctor_id) or {}
    all_doctors = _get_doctors()
    all_specialties = _get_specialties()

    # Build context for template
    patient_display = {
        "name": patient.get("name", "Không rõ"),
        "age": calculate_age(patient.get("birthdate", "")),
        "gender": normalize_gender(patient.get("gender", "")),
        "phone": patient.get("phone", ""),
        "birthdate": patient.get("birthdate", ""),
    }

    appointment_display = {
        "id": appointment_id,
        "date": appointment.get("date", ""),
        "specialty": appointment.get("specialtyName", ""),
        "reason": appointment.get("reason", ""),
        "status": appointment.get("status", ""),
    }

    if request.method == "POST":
        target_doctor_id = (request.POST.get("target_doctor_id") or "").strip()
        target_specialty_id = (request.POST.get("target_specialty_id") or "").strip()
        referral_date = (request.POST.get("referral_date") or "").strip() or date.today().isoformat()
        session = (request.POST.get("session") or "morning").strip()
        reason = (request.POST.get("reason") or "").strip()
        priority_note = (request.POST.get("priority_note") or "").strip()

        errors = []
        if not target_doctor_id:
            errors.append("Vui lòng chọn bác sĩ tiếp nhận.")
        if not reason:
            errors.append("Vui lòng nhập lý do chuyển.")

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "appointments/referral.html", {
                "patient": patient_display,
                "appointment": appointment_display,
                "all_doctors": all_doctors,
                "all_specialties": all_specialties,
                "form_data": {
                    "target_doctor_id": target_doctor_id,
                    "target_specialty_id": target_specialty_id,
                    "referral_date": referral_date,
                    "session": session,
                    "reason": reason,
                    "priority_note": priority_note,
                },
            })

        # Resolve target doctor info
        target_doctor = _get_doctor(target_doctor_id) or {}
        target_doctor_name = target_doctor.get("name", "")

        # Resolve specialty info
        target_specialty_name = ""
        if target_specialty_id:
            for spec in all_specialties:
                if str(spec.get("id", "")) == target_specialty_id:
                    target_specialty_name = spec.get("name", "")
                    break
        elif target_doctor:
            target_specialty_id = target_doctor.get("specialtyID", "")
            for spec in all_specialties:
                if str(spec.get("id", "")) == target_specialty_id:
                    target_specialty_name = spec.get("name", "")
                    break

        referral_data = {
            "date": referral_date,
            "session": session,
            "reason": reason,
            "priority_note": priority_note,
            "source_doctor_id": doctor_id,
            "source_doctor_name": source_doctor.get("name", ""),
            "patient_id": patient_id,
            "target_doctor_name": target_doctor_name,
            "target_specialty_id": target_specialty_id,
            "target_specialty_name": target_specialty_name,
        }

        created = create_referral_appointment(appointment_id, target_doctor_id, referral_data)

        if not created:
            messages.error(request, "Không thể tạo lịch chuyển. Vui lòng thử lại.")
            return render(request, "appointments/referral.html", {
                "patient": patient_display,
                "appointment": appointment_display,
                "all_doctors": all_doctors,
                "all_specialties": all_specialties,
                "form_data": {
                    "target_doctor_id": target_doctor_id,
                    "target_specialty_id": target_specialty_id,
                    "referral_date": referral_date,
                    "session": session,
                    "reason": reason,
                    "priority_note": priority_note,
                },
            })

        # Invalidate dashboard cache for target doctor
        try:
            invalidate_dashboard_cache(doctor_id=target_doctor_id, selected_date_iso=referral_date)
        except Exception:
            pass

        messages.success(request, f"Đã chuyển hồ sơ bệnh nhân đến BS. {target_doctor_name} thành công.")
        return redirect("dashboard")

    # GET request
    return render(request, "appointments/referral.html", {
        "patient": patient_display,
        "appointment": appointment_display,
        "all_doctors": all_doctors,
        "all_specialties": all_specialties,
        "form_data": {
            "target_doctor_id": "",
            "target_specialty_id": "",
            "referral_date": date.today().isoformat(),
            "session": "morning",
            "reason": "",
            "priority_note": "",
        },
    })


def create_appointment_view(request):
    if request.session.get("admin_portal_user_id"):
        return redirect("admin_portal_dashboard")

    doctor_id = request.session.get("doctor_id")
    if not doctor_id:
        return redirect("login")

    patient_id = (request.GET.get("patient_id") or request.POST.get("patient_id") or "").strip()
    if not patient_id:
        messages.error(request, "Thiếu bệnh nhân để đặt lịch.")
        return redirect("add_patient")

    patient = get_patient_by_id(patient_id)
    if not patient:
        messages.error(request, "Không tìm thấy bệnh nhân để đặt lịch.")
        return redirect("add_patient")

    doctor = get_doctor_by_id(doctor_id) or {}
    specialty = get_specialty_by_id(doctor.get("specialtyID", "")) if doctor else {}
    specialty = specialty or {}
    specialties = get_all_specialties()
    hospitals = get_all_hospitals()
    specialty_map = {
        str(item.get("id", "")).strip(): item
        for item in specialties
        if str(item.get("id", "")).strip()
    }

    # Default location is the doctor's hospital
    doctor_hospital_id = (doctor.get("hospitalID") or "").strip()

    form_data = {
        "appointment_date": date.today().isoformat(),
        "session": "morning",
        "status": "Đã đến",
        "booking_type": "walk-in",
        "international": "",
        "reason": "",
        "notes": "",
        "location": doctor_hospital_id,
        "specialty_id": (doctor.get("specialtyID") or "").strip(),
    }
    if not form_data["specialty_id"] and specialties:
        form_data["specialty_id"] = str(specialties[0].get("id", "")).strip()

    if request.method == "POST":
        form_data.update({
            "appointment_date": (request.POST.get("appointment_date") or "").strip(),
            "session": (request.POST.get("session") or "").strip() or "morning",
            "status": "Đã đến",
            "booking_type": "walk-in",
            "international": request.POST.get("international", ""),
            "reason": (request.POST.get("reason") or "").strip(),
            "notes": (request.POST.get("notes") or "").strip(),
            "location": (request.POST.get("location") or "").strip(),
            "specialty_id": (request.POST.get("specialty_id") or "").strip(),
        })

        errors = []
        if not form_data["appointment_date"]:
            errors.append("Vui lòng chọn ngày khám.")
        if form_data["session"] not in {"morning", "afternoon"}:
            errors.append("Vui lòng chọn buổi khám.")
        if not form_data["specialty_id"]:
            errors.append("Vui lòng chọn khoa khám.")
        elif form_data["specialty_id"] not in specialty_map:
            errors.append("Khoa đã chọn không hợp lệ.")
        if not form_data["reason"]:
            errors.append("Vui lòng nhập lý do khám.")

        if errors:
            for error_message in errors:
                messages.error(request, error_message)
            return render(
                request,
                "appointments/create_appointment.html",
                {
                    "patient": patient,
                    "doctor": doctor,
                    "specialty": specialty,
                    "specialties": specialties,
                    "hospitals": hospitals,
                    "form_data": form_data,
                },
            )

        session_key = form_data["session"]
        selected_specialty = specialty_map.get(form_data["specialty_id"], {})

        created_appointment = create_walk_in_appointment(
            {
                "date": form_data["appointment_date"],
                "time": "",
                "session": session_key,
                "doctor_id": doctor_id,
                "doctor_name": (doctor.get("name") or "").strip(),
                "specialty_id": form_data["specialty_id"],
                "specialty_name": (selected_specialty.get("name") or "").strip(),
                "patient_id": patient_id,
                "status": form_data["status"],
                "reason": form_data["reason"],
                "notes": form_data["notes"],
                "location": form_data["location"],
                "international": bool(form_data["international"]),
                "booking_type": form_data["booking_type"],
                "user_id": (patient.get("userID") or patient_id).strip(),
            }
        )

        if not created_appointment:
            messages.error(request, "Không thể tạo lịch khám cho bệnh nhân.")
            return render(
                request,
                "appointments/create_appointment.html",
                {
                    "patient": patient,
                    "doctor": doctor,
                    "specialty": specialty,
                    "specialties": specialties,
                    "hospitals": hospitals,
                    "form_data": form_data,
                },
            )

        # Invalidate dashboard cache so the new appointment appears immediately.
        try:
            invalidate_dashboard_cache(
                doctor_id=doctor_id,
                selected_date_iso=form_data["appointment_date"],
            )
        except Exception as inv_err:
            print(f"⚠️ create_appointment cache invalidation failed: {inv_err}")

        # Add to queue (since status is "Đã đến", patient is already checked in)
        try:
            appointment_id = created_appointment.get("id") or created_appointment.get("appointmentID", "")
            now_iso = datetime.now().isoformat()

            # Record arrival time on the appointment
            from services.RTDB_utils import update_appointment as _update_apt
            _update_apt(appointment_id, arrivalTime=now_iso)

            # Create queue token
            queue_date = form_data["appointment_date"]
            queue_ref = db.child("queues").child(doctor_id).child(queue_date)
            existing_tokens = queue_ref.get() or {}
            next_position = len(existing_tokens) + 1 if isinstance(existing_tokens, dict) else 1

            queue_token = {
                "appointmentID": appointment_id,
                "patientID": patient_id,
                "patientName": patient.get("name", ""),
                "phone": patient.get("phone", ""),
                "session": form_data["session"],
                "status": "waiting",
                "queueStatus": "waiting",
                "position": next_position,
                "queueNumber": next_position,
                # Stable original number — never changes when priority is toggled.
                # See _apply_queue_priority_score in RTDB_utils.py for usage.
                "originalQueueNumber": next_position,
                "arrivedAt": now_iso,
                "createdAt": int(time.time() * 1000),
            }
            queue_ref.push(queue_token)
        except Exception as q_err:
            print(f"⚠️ create_appointment queue token failed: {q_err}")

        # Notify queue advance (new patient in queue may trigger notification)
        try:
            notify_queue_advance(doctor_id, form_data["appointment_date"])
        except Exception:
            pass

        messages.success(request, "Đã thêm bệnh nhân vào hàng đợi khám.")
        query = urlencode({"date": form_data["appointment_date"]})
        return redirect(f"/appointments/dashboard/?{query}")

    return render(
        request,
        "appointments/create_appointment.html",
        {
            "patient": patient,
            "doctor": doctor,
            "specialty": specialty,
            "specialties": specialties,
            "hospitals": hospitals,
            "form_data": form_data,
        },
    )

