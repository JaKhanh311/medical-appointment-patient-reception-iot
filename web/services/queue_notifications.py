"""
Queue Notification Service
Ghi thông báo vào Firebase RTDB + gửi FCM push trực tiếp từ Django.
App Android nhận push notification kể cả khi app tắt.

Logic gửi thông báo:
- Khi bệnh nhân ở vị trí 4 trong hàng đợi (còn 3 người phía trước) → gửi 1 lần
- Cờ `notifyFlags.almostSent` lưu trên appointment để chống gửi trùng
- Set cờ TRƯỚC khi gửi để tránh race condition khi nhiều trigger chạy đồng thời
"""
import time
from firebase_admin import messaging
from services.firebase import db


QUEUE_ALMOST_THRESHOLD = 3  # Còn 3 người phía trước → gửi thông báo


def _doctor_key_variants(doctor_id: str) -> list:
    """Trả về cả 2 dạng doctor key: 'doc_001' và '001' để xử lý dữ liệu cũ/mới."""
    doctor_id = str(doctor_id or "").strip()
    if not doctor_id:
        return []
    variants = [doctor_id]
    if doctor_id.startswith("doc_"):
        variants.append(doctor_id[4:])
    else:
        variants.append(f"doc_{doctor_id}")
    return list(dict.fromkeys(variants))  # dedupe, giữ thứ tự


def notify_queue_advance(doctor_id: str, selected_date_iso: str):
    """
    Tính lại vị trí queue sau khi có thay đổi (khám xong, check-in mới).
    Gửi thông báo cho bệnh nhân ở vị trí thứ (THRESHOLD + 1) nếu chưa gửi.
    """
    try:
        doctor_id = str(doctor_id or "").strip()
        selected_date_iso = str(selected_date_iso or "").strip()
        if not doctor_id or not selected_date_iso:
            return

        # Normalize date to YYYY-MM-DD (Firebase path cannot contain '/')
        if '/' in selected_date_iso:
            try:
                from datetime import datetime as _dt
                for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"):
                    try:
                        selected_date_iso = _dt.strptime(selected_date_iso, fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
            except Exception:
                pass
        
        print(f"[NOTIFY] notify_queue_advance(doctor={doctor_id}, date={selected_date_iso})")

        # 1. Lấy danh sách waiting đã sắp xếp theo thứ tự queue
        waiting_appointments, doctor_key_used = _get_waiting_appointments_sorted(doctor_id, selected_date_iso)
        if not waiting_appointments:
            print(f"[NOTIFY] No waiting appointments for {doctor_id}/{selected_date_iso}")
            return

        # Gửi notification cho bệnh nhân ở vị trí mà phía trước có đúng THRESHOLD người.
        # Vì notify chạy SAU khi bệnh nhân trước đã completed (bị loại khỏi waiting list),
        # ta cần gửi cho người ở vị trí THRESHOLD (không phải THRESHOLD+1).
        # Ví dụ: THRESHOLD=3, gửi cho người ở vị trí 3 (còn 2 người trước trong waiting,
        # nhưng thực tế còn 3 người trước nếu tính cả người vừa khám xong).
        target_position = QUEUE_ALMOST_THRESHOLD  # vị trí 3 (0-indexed = 2)
        print(f"[NOTIFY] Queue has {len(waiting_appointments)} waiting patients, target position = {target_position}")
        
        if len(waiting_appointments) < target_position:
            print(f"[NOTIFY] Not enough patients ({len(waiting_appointments)} < {target_position}), skip")
            return

        target_apt = waiting_appointments[target_position - 1]  # 0-indexed
        appointment_id = str(target_apt.get("id") or target_apt.get("appointmentID") or "").strip()
        if not appointment_id:
            print(f"[NOTIFY] Target appointment has no ID, skip")
            return

        # 2. Check cờ almostSent — đã gửi chưa?
        notify_flags = target_apt.get("notifyFlags") or target_apt.get("notifications") or {}
        if isinstance(notify_flags, dict) and notify_flags.get("almostSent"):
            print(f"[NOTIFY] Already sent for {appointment_id} (almostSent=true), skip")
            return  # Đã gửi rồi, skip
        
        print(f"[NOTIFY] Target: apt={appointment_id}, patient={target_apt.get('patientID')}, notifyFlags={notify_flags}")

        # 3. RACE-CONDITION GUARD: set cờ TRƯỚC khi gửi
        # Nếu nhiều trigger chạy song song, chỉ trigger đầu tiên qua được bước này.
        # Trigger sau sẽ thấy cờ đã set ở bước 2 và skip.
        now_ms = int(time.time() * 1000)
        flag_ref = db.child("appointment_new").child(doctor_key_used).child(selected_date_iso).child(appointment_id).child("notifyFlags")
        try:
            flag_ref.update({
                "almostSent": True,
                "almostSentAt": now_ms,
            })
        except Exception as flag_err:
            print(f"⚠️ notify flag set failed: {flag_err}")
            return  # Không thể set cờ → bỏ qua để tránh gửi trùng

        # 4. Lấy userID của bệnh nhân
        patient_id = str(target_apt.get("patientID") or "").strip()
        user_id = str(target_apt.get("userID") or "").strip()
        if not user_id and patient_id:
            try:
                patient_data = db.child("patients").child(patient_id).get()
                if isinstance(patient_data, dict):
                    user_id = str(patient_data.get("userID") or "").strip()
            except Exception:
                pass
        if not user_id:
            user_id = patient_id  # Fallback cuối: dùng patientID

        if not user_id:
            print(f"[NOTIFY] No user_id for appointment {appointment_id}, skip")
            return

        # 5. Lấy thông tin bác sĩ
        doctor_data = db.child("doctors").child(doctor_id).get() or {}
        if not isinstance(doctor_data, dict):
            doctor_data = {}
        doctor_name = str(doctor_data.get("name") or "").strip()
        specialty_id = str(doctor_data.get("specialtyID") or "").strip()
        specialty_name = ""
        if specialty_id:
            try:
                spec_data = db.child("specialties").child(specialty_id).get()
                if isinstance(spec_data, dict):
                    specialty_name = str(spec_data.get("name") or "").strip()
            except Exception:
                pass

        # 5b. Lấy tên bệnh nhân
        patient_name = str(target_apt.get("patientName") or "").strip()
        if not patient_name and patient_id:
            try:
                p_data = db.child("patients").child(patient_id).get()
                if isinstance(p_data, dict):
                    patient_name = str(p_data.get("name") or "").strip()
            except Exception:
                pass

        # 6. Tạo notification payload
        notification_payload = {
            "type": "queue_almost",
            "title": "Sắp đến lượt khám",
            "body": f"Chào quý khách {patient_name}, còn {QUEUE_ALMOST_THRESHOLD} người nữa sẽ đến lượt khám của bạn, hãy quay trở lại phòng khám của bác sĩ {doctor_name}.",
            "appointmentID": appointment_id,
            "doctorName": doctor_name,
            "specialtyName": specialty_name,
            "position": target_position,
            "createdAt": now_ms,
            "read": False,
        }

        # 7. Ghi vào RTDB notifications/{userID} để app hiển thị danh sách
        try:
            db.child("notifications").child(user_id).push(notification_payload)
        except Exception as write_err:
            print(f"⚠️ notification write failed: {write_err}")

        # 8. Gửi FCM push
        _send_fcm_push(user_id, notification_payload)

        print(f"[NOTIFY] Sent queue_almost to user={user_id} apt={appointment_id} pos={target_position}")

    except Exception as e:
        print(f"⚠️ notify_queue_advance error: {e}")


def _send_fcm_push(user_id: str, notification_data: dict):
    """Gửi FCM push notification trực tiếp từ Django bằng firebase-admin SDK."""
    try:
        token_data = db.child("fcm_tokens").child(user_id).get()
        if not isinstance(token_data, dict):
            print(f"[FCM] No FCM token for {user_id}, skip push (notification still in RTDB)")
            return

        fcm_token = str(token_data.get("token") or "").strip()
        if not fcm_token:
            return

        message = messaging.Message(
            token=fcm_token,
            notification=messaging.Notification(
                title=notification_data.get("title", "Thông báo"),
                body=notification_data.get("body", ""),
            ),
            data={
                "type": str(notification_data.get("type", "general")),
                "appointmentID": str(notification_data.get("appointmentID", "")),
                "doctorName": str(notification_data.get("doctorName", "")),
                "specialtyName": str(notification_data.get("specialtyName", "")),
                "position": str(notification_data.get("position", 0)),
                "createdAt": str(notification_data.get("createdAt", 0)),
            },
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="queue_notifications",
                    priority="high",
                    default_sound=True,
                    default_vibrate_timings=True,
                ),
            ),
        )

        response = messaging.send(message)
        print(f"[FCM] Push sent to {user_id}: {response}")

    except messaging.UnregisteredError:
        print(f"[FCM] Token invalid for {user_id}, removing...")
        try:
            db.child("fcm_tokens").child(user_id).delete()
        except Exception:
            pass
    except Exception as e:
        print(f"⚠️ FCM push error for {user_id}: {e}")


def _get_waiting_appointments_sorted(doctor_id: str, selected_date_iso: str):
    """
    Lấy danh sách appointments đang waiting cho doctor/date,
    sắp xếp theo: priority (priority lên trước) → arrival time (FCFS).

    Returns: (waiting_list, doctor_key_used)
    """
    try:
        waiting = []
        doctor_key_used = ""

        for dk in _doctor_key_variants(doctor_id):
            try:
                day_node = db.child("appointment_new").child(dk).child(selected_date_iso).get() or {}
            except Exception as e:
                print(f"[NOTIFY] Error reading appointment_new/{dk}/{selected_date_iso}: {e}")
                continue

            if not isinstance(day_node, dict) or not day_node:
                print(f"[NOTIFY] No data at appointment_new/{dk}/{selected_date_iso}")
                continue

            doctor_key_used = dk
            print(f"[NOTIFY] Found {len(day_node)} appointments at appointment_new/{dk}/{selected_date_iso}")

            for apt_id, apt_data in day_node.items():
                if not isinstance(apt_data, dict):
                    continue

                status = str(apt_data.get("status") or "").strip().lower()
                # Các trạng thái "đang chờ khám"
                if status not in ("đã đến", "da den", "waiting", "arrived"):
                    continue

                apt_data["id"] = apt_id
                waiting.append(apt_data)

            if waiting:
                print(f"[NOTIFY] Found {len(waiting)} waiting patients with key '{dk}'")
                break  # Đã tìm thấy data với key này, không cần check key khác
            else:
                print(f"[NOTIFY] 0 waiting patients at appointment_new/{dk}/{selected_date_iso} (statuses: {[str(v.get('status',''))[:10] for v in day_node.values() if isinstance(v, dict)][:5]})")

        # Sort: priority trước, rồi FCFS
        def sort_key(apt):
            priority_data = apt.get("priority") or {}
            is_priority = bool(priority_data.get("status", False)) if isinstance(priority_data, dict) else False
            priority_bucket = 0 if is_priority else 1

            arrival = (
                apt.get("arrivalTime")
                or apt.get("checkedInAt")
                or apt.get("arrivedAt")
                or ""
            )
            arrival_ts = _parse_timestamp(arrival)
            return (priority_bucket, arrival_ts)

        waiting.sort(key=sort_key)
        return waiting, doctor_key_used

    except Exception as e:
        print(f"⚠️ _get_waiting_appointments_sorted error: {e}")
        return [], ""


def _parse_timestamp(value) -> int:
    """Parse various timestamp formats to comparable int (seconds)."""
    if not value:
        return 10**15

    if isinstance(value, (int, float)):
        v = int(value)
        return v // 1000 if v > 10**12 else v

    text = str(value).strip()
    if text.isdigit():
        v = int(text)
        return v // 1000 if v > 10**12 else v

    try:
        from datetime import datetime
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return 10**15
