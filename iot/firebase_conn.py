from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional

import firebase_admin
from firebase_admin import credentials, db
from dotenv import load_dotenv


_initialized = False
_ROOT_DIR = Path(__file__).resolve().parent
_ENV_PATH = _ROOT_DIR / ".env"


def _resolve_cred_path(raw_path: str) -> str:
    p = Path(raw_path.strip())
    if p.is_absolute():
        return str(p)
    # Prefer resolving relative to IoT root where .env and JSON usually live.
    candidate = (_ROOT_DIR / p).resolve()
    if candidate.exists():
        return str(candidate)
    # Fallback to current working directory behavior for compatibility.
    return str(p)


def _init_firebase() -> None:
    global _initialized
    if _initialized:
        return

    load_dotenv(dotenv_path=_ENV_PATH)
    cred_path = os.getenv("FIREBASE_CRED_JSON")
    db_url = os.getenv("FIREBASE_DB_URL")

    if not cred_path or not db_url:
        raise RuntimeError(
            "Missing FIREBASE_CRED_JSON or FIREBASE_DB_URL in environment"
        )

    resolved_cred_path = _resolve_cred_path(cred_path)
    if not Path(resolved_cred_path).exists():
        raise FileNotFoundError(
            f"Không tìm thấy file credentials: {resolved_cred_path}"
        )

    cred = credentials.Certificate(resolved_cred_path)
    firebase_admin.initialize_app(cred, {"databaseURL": db_url})
    _initialized = True


def get_db_ref(path: str = "") -> db.Reference:
    _init_firebase()
    return db.reference(path)


def reset_firebase_connection() -> None:
    """Reset Firebase app state so new env settings can be applied."""
    global _initialized
    if _initialized:
        try:
            firebase_admin.delete_app(firebase_admin.get_app())
        except Exception:
            pass
    _initialized = False


def get_patient(patient_id: str, base_path: str = "patients") -> Optional[Any]:
    if not patient_id:
        return None
    ref = get_db_ref(f"{base_path}/{patient_id}")
    return ref.get()


def update_patient_status(
    patient_id: str, status: str, base_path: str = "patients"
) -> bool:
    """Update patient status in Firebase"""
    if not patient_id:
        return False
    try:
        ref = get_db_ref(f"{base_path}/{patient_id}")
        ref.update({"status": status})
        return True
    except Exception as e:
        print(f"Error updating patient status: {e}")
        return False


def update_appointment_status(
    patient_id: str,
    appointment_id: str,
    status: str,
    base_path: str = "patients",
) -> bool:
    """Update the status of a specific appointment under a patient.

    The database is assumed to store appointments as
    ``/patients/{patient_id}/appointments/{appointment_id}``.  This helper
    will write only the ``status`` field so other appointment data is left
    untouched.
    """
    if not patient_id or not appointment_id:
        return False
    try:
        ref = get_db_ref(f"{base_path}/{patient_id}/appointments/{appointment_id}")
        ref.update({"status": status})
        return True
    except Exception as e:
        print(f"Error updating appointment status: {e}")
        return False


def get_appointments_for_patient(
    patient_id: str, base_path: str = "appointment_new"
) -> list[dict]:
    """Return a list of appointment records for the given patient.

    When using Firebase Realtime Database we attempt to perform a query
    filtering by ``patientID``; if that fails we fall back to downloading
    the entire appointments node and filtering in Python.  Each returned
    dictionary includes an ``id`` key corresponding to the appointment's
    database key.
    """
    if not patient_id:
        return []
    if base_path == "appointment_new":
        snapshot = get_db_ref(base_path).get()
        appointments = []
        if not isinstance(snapshot, dict):
            return appointments

        for doctor_id, doctor_bucket in snapshot.items():
            if not isinstance(doctor_bucket, dict):
                continue
            for date_key, date_bucket in doctor_bucket.items():
                if not isinstance(date_bucket, dict):
                    continue
                for appt_id, appt in date_bucket.items():
                    if not isinstance(appt, dict):
                        continue
                    appt_patient_id = (
                        appt.get("patientID")
                        or appt.get("patientId")
                        or appt.get("patient_id")
                    )
                    if str(appt_patient_id) != str(patient_id):
                        continue
                    entry = dict(appt)
                    entry["id"] = appt_id
                    entry.setdefault("doctorID", doctor_id)
                    entry.setdefault("date", date_key)
                    appointments.append(entry)
        return appointments

    try:
        ref = get_db_ref(base_path)
        # perform a simple query; this requires the underlying data to be
        # indexed on patientID in the database rules but is otherwise cheap.
        snapshot = ref.order_by_child("patientID").equal_to(patient_id).get()
    except Exception:
        # query failed (e.g. because admin SDK doesn't support it); read all
        snapshot = get_db_ref(base_path).get()
    appointments = []
    if isinstance(snapshot, dict):
        for appt_id, appt in snapshot.items():
            if isinstance(appt, dict):
                # always verify patientID matches in case we had to fall back
                if appt.get("patientID") != patient_id:
                    continue
                entry = dict(appt)
                entry["id"] = appt_id
                appointments.append(entry)
    return appointments


def _find_appointment_new_path(appointment_id: str, base_path: str = "appointment_new") -> Optional[str]:
    if not appointment_id:
        return None

    lookup = get_db_ref(f"appointment_new_lookup/{appointment_id}").get()
    if isinstance(lookup, dict):
        doctor_id = lookup.get("doctorID") or lookup.get("doctorId") or lookup.get("doctor_id")
        date_key = lookup.get("date") or lookup.get("appointmentDate")
        if doctor_id and date_key:
            return f"{base_path}/{doctor_id}/{date_key}/{appointment_id}"

    snapshot = get_db_ref(base_path).get()
    if not isinstance(snapshot, dict):
        return None

    for doctor_id, doctor_bucket in snapshot.items():
        if not isinstance(doctor_bucket, dict):
            continue
        for date_key, date_bucket in doctor_bucket.items():
            if not isinstance(date_bucket, dict):
                continue
            if appointment_id in date_bucket:
                return f"{base_path}/{doctor_id}/{date_key}/{appointment_id}"
    return None


def get_appointment(appointment_id: str, base_path: str = "appointment_new") -> Optional[Any]:
    """Return a single appointment record by its ID."""
    if not appointment_id:
        return None
    if base_path == "appointment_new":
        appt_path = _find_appointment_new_path(appointment_id, base_path=base_path)
        if not appt_path:
            return None
        return get_db_ref(appt_path).get()
    ref = get_db_ref(f"{base_path}/{appointment_id}")
    return ref.get()


def update_global_appointment_status(
    appointment_id: str, status: str, base_path: str = "appointment_new"
) -> bool:
    """Set the ``status`` field of an appointment at the global appointments root.

    This is separate from ``update_appointment_status`` which updates a nested
    appointment under a patient entry.  Use this when appointments are stored
    under ``/appointments``.
    """
    if not appointment_id:
        return False
    try:
        if base_path == "appointment_new":
            appt_path = _find_appointment_new_path(appointment_id, base_path=base_path)
            if not appt_path:
                return False
            ref = get_db_ref(appt_path)
        else:
            ref = get_db_ref(f"{base_path}/{appointment_id}")
        ref.update({"status": status})
        return True
    except Exception as e:
        print(f"Error updating global appointment status: {e}")
        return False


def update_global_appointment_fields(
    appointment_id: str,
    updates: dict[str, Any],
    base_path: str = "appointment_new",
) -> bool:
    """Update arbitrary appointment fields by appointment id."""
    if not appointment_id or not isinstance(updates, dict) or not updates:
        return False

    try:
        if base_path == "appointment_new":
            appt_path = _find_appointment_new_path(appointment_id, base_path=base_path)
            if not appt_path:
                return False
            ref = get_db_ref(appt_path)
        else:
            ref = get_db_ref(f"{base_path}/{appointment_id}")
        ref.update(updates)
        return True
    except Exception as e:
        print(f"Error updating appointment fields: {e}")
        return False


def add_patient_to_queue(
    appointment_id: str,
    patient_id: str,
    patient_name: str,
    doctor_id: str,
    priority_type: str = "normal",
    priority_level: int = 50,
    queues_path: str = "queues",
    queue_meta_path: str = "queue_meta",
) -> int:
    """Atomically assign the next queue number for the doctor and create the queue entry.

    Queue numbers are reset per day by storing counters under
    ``queue_meta/{doctor_id}/{YYYY-MM-DD}`` and queue entries under
    ``queues/{doctor_id}/{YYYY-MM-DD}/q_{N:03d}``.

    Returns the assigned queue number, or -1 on failure.
    """
    if not appointment_id or not patient_id or not doctor_id:
        return -1

    _init_firebase()

    queue_bucket = time.strftime("%Y-%m-%d", time.localtime())
    meta_ref = get_db_ref(f"{queue_meta_path}/{doctor_id}/{queue_bucket}")

    assigned_number: list[int] = []

    def _increment(current_data: Optional[Any]) -> Any:
        if current_data is None:
            current_data = {
                "queueDate": queue_bucket,
                "lastQueueNumber": 0,
                "currentlyServing": 0,
                "waitingCount": 0,
            }
        current_data["queueDate"] = queue_bucket
        current_data["lastQueueNumber"] = int(current_data.get("lastQueueNumber", 0)) + 1
        current_data["waitingCount"] = int(current_data.get("waitingCount", 0)) + 1
        assigned_number.append(int(current_data["lastQueueNumber"]))
        return current_data

    try:
        meta_ref.transaction(_increment)
    except Exception as e:
        print(f"Error updating queue_meta for {doctor_id}: {e}")
        return -1

    if not assigned_number:
        return -1

    queue_number = assigned_number[0]
    queue_key = f"q_{queue_number:03d}"
    arrived_ts = int(time.time())

    queue_entry = {
        "appointmentId": appointment_id,
        "patientId": patient_id,
        "patientName": patient_name,
        "queueDate": queue_bucket,
        "queueNumber": queue_number,
        # Stable original number — never changes when priority is toggled on
        # the doctor dashboard. See _apply_queue_priority_score in the web
        # backend (services/RTDB_utils.py) for usage.
        "originalQueueNumber": queue_number,
        "priorityType": priority_type,
        "priorityLevel": priority_level,
        "status": "waiting",
        "arrivedAt": arrived_ts,
        "calledAt": None,
        "completedAt": None,
    }

    try:
        get_db_ref(f"{queues_path}/{doctor_id}/{queue_bucket}/{queue_key}").set(queue_entry)
    except Exception as e:
        print(f"Error writing queue entry {queue_key} for {doctor_id}: {e}")
        return -1

    return queue_number


if __name__ == "__main__":
    # Quick manual test: set env vars then run
    # python firebase_conn.py PATIENT_ID
    import sys
    from pprint import pprint

    pid = sys.argv[1] if len(sys.argv) > 1 else ""
    data = get_patient(pid)
    pprint(data)