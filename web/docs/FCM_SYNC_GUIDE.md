# Hướng dẫn đồng bộ FCM Token & Notifications giữa Web và App

## Tổng quan

Hệ thống OPDFlow sử dụng Firebase Realtime Database (RTDB) làm trung gian để đồng bộ thông báo giữa:
- **Web Django** (ghi notification + gửi FCM push)
- **App Android** (lưu FCM token + nhận push + đọc danh sách thông báo)

```
┌──────────────┐                    ┌──────────────────┐                    ┌──────────────┐
│  App Android │ ── lưu token ────→ │  Firebase RTDB   │ ←── đọc token ──── │    Django    │
│              │                    │                  │                    │              │
│              │ ←── push FCM ───── │  fcm_tokens/     │                    │              │
│              │                    │  notifications/  │ ←── ghi notif ──── │              │
│              │ ── listen ───────→ │                  │                    │              │
└──────────────┘                    └──────────────────┘                    └──────────────┘
```

---

## 1. Cấu trúc dữ liệu trên Firebase RTDB

### 1.1. `fcm_tokens/{userID}`

**Ai ghi:** App Android (khi đăng nhập hoặc token refresh)
**Ai đọc:** Django (khi cần gửi push notification)

```json
fcm_tokens/
  "uid_abc123"/                    ← Firebase Auth UID của bệnh nhân
    "token": "fGxK7...:APA91b..." ← FCM registration token
    "platform": "android"
    "updatedAt": 1716200000000     ← timestamp ms khi cập nhật
```

**Quy tắc key `{userID}`:**
- Là **Firebase Auth UID** của bệnh nhân (lấy từ `FirebaseAuth.getInstance().currentUser.uid`)
- Phải khớp với field `userID` trong appointment khi bệnh nhân đặt lịch
- Nếu bệnh nhân chưa có Firebase Auth account → dùng `patientID` làm fallback

### 1.2. `notifications/{userID}/{pushKey}`

**Ai ghi:** Django (khi queue advance, bệnh nhân sắp tới lượt)
**Ai đọc:** App Android (listen realtime + hiển thị danh sách)
**Ai update:** App Android (đánh dấu `read: true`)

```json
notifications/
  "uid_abc123"/
    "-OtXyz123"/                   ← Firebase push key (auto-generated)
      "type": "queue_almost"
      "title": "Sắp đến lượt khám"
      "body": "Còn 3 người phía trước bạn. Vui lòng có mặt tại phòng khám."
      "appointmentID": "-Os4_yKmf..."
      "doctorName": "BS. Ngô Hữu Tài"
      "specialtyName": "Khoa Huyết Học"
      "position": 4
      "createdAt": 1716200000000
      "read": false                ← App set true khi user đã đọc
```

---

## 2. Luồng đồng bộ chi tiết

### 2.1. App lưu FCM Token (khi đăng nhập)

```
App khởi động
  → FirebaseAuth.signIn(email, password)
  → Lấy currentUser.uid
  → FirebaseMessaging.getInstance().token
  → Ghi vào RTDB: fcm_tokens/{uid}/token = "..."
```

**Kotlin code:**
```kotlin
fun registerFcmToken() {
    val uid = FirebaseAuth.getInstance().currentUser?.uid ?: return
    
    FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
        FirebaseDatabase.getInstance()
            .getReference("fcm_tokens")
            .child(uid)
            .setValue(mapOf(
                "token" to token,
                "platform" to "android",
                "updatedAt" to ServerValue.TIMESTAMP
            ))
    }
}
```

**Khi nào gọi:**
- Sau login thành công
- Trong `Application.onCreate()` nếu user đã đăng nhập
- Trong `onNewToken()` khi FCM refresh token

### 2.2. Django đọc token và gửi push (khi queue advance)

```
Bác sĩ khám xong bệnh nhân
  → notify_queue_advance(doctor_id, date)
  → Tìm bệnh nhân ở vị trí 4
  → Lấy userID từ appointment hoặc patient
  → Đọc: fcm_tokens/{userID}/token
  → Gửi FCM push bằng firebase-admin SDK
  → Ghi: notifications/{userID}/{pushKey} = {...}
```

**Python code (đã có trong `services/queue_notifications.py`):**
```python
# Đọc token
token_data = db.child("fcm_tokens").child(user_id).get()
fcm_token = token_data.get("token")

# Gửi push
message = messaging.Message(token=fcm_token, ...)
messaging.send(message)

# Ghi notification vào RTDB
db.child("notifications").child(user_id).push(notification_payload)
```

### 2.3. App nhận push + đọc notifications

```
FCM push đến
  → onMessageReceived() → hiển thị system notification
  
User mở app
  → Listen: notifications/{uid} (orderByChild "read" == false)
  → Hiển thị danh sách thông báo chưa đọc
  
User tap thông báo
  → Update: notifications/{uid}/{key}/read = true
```

---

## 3. Mapping userID giữa Web và App

### Vấn đề: Làm sao Django biết userID nào để gửi?

Khi bệnh nhân đặt lịch trên app, appointment được tạo với:
```json
{
  "patientID": "pat_001",
  "userID": "uid_abc123",    ← Firebase Auth UID
  ...
}
```

Django lấy `userID` theo thứ tự:
1. `appointment.userID` (ưu tiên nhất)
2. `patients/{patientID}/userID` (fallback)
3. `patientID` (fallback cuối)

### Đảm bảo đồng bộ:

| Phía | Hành động | Key sử dụng |
|------|-----------|-------------|
| App đặt lịch | Ghi `userID` vào appointment | `FirebaseAuth.currentUser.uid` |
| App lưu token | Ghi vào `fcm_tokens/{uid}` | `FirebaseAuth.currentUser.uid` |
| Django gửi push | Đọc `fcm_tokens/{userID}` | `appointment.userID` |

**→ Cả 2 phía đều dùng `FirebaseAuth.currentUser.uid` làm key → tự động khớp.**

---

## 4. Firebase Security Rules

```json
{
  "rules": {
    "fcm_tokens": {
      "$uid": {
        ".read": "$uid === auth.uid",
        ".write": "$uid === auth.uid"
      }
    },
    "notifications": {
      "$uid": {
        ".read": "$uid === auth.uid",
        ".write": false,
        "$pushKey": {
          "read": {
            ".write": "$uid === auth.uid"
          },
          "readAt": {
            ".write": "$uid === auth.uid"
          }
        }
      }
    }
  }
}
```

**Giải thích:**
- `fcm_tokens/{uid}`: chỉ user đó mới đọc/ghi token của mình
- `notifications/{uid}`: chỉ user đó mới đọc thông báo của mình
- `notifications/{uid}/{key}/read`: user chỉ được update field `read` (đánh dấu đã đọc)
- Django dùng firebase-admin SDK → bypass rules hoàn toàn (server-side)

---

## 5. Xử lý edge cases

### 5.1. Token hết hạn / App bị gỡ

Django xử lý tự động:
```python
except messaging.UnregisteredError:
    # Token không hợp lệ → xóa khỏi RTDB
    db.child("fcm_tokens").child(user_id).delete()
```

App cần gọi `registerFcmToken()` lại khi cài lại app.

### 5.2. User đăng nhập trên thiết bị mới

`onNewToken()` được gọi → ghi đè token cũ:
```kotlin
override fun onNewToken(token: String) {
    val uid = FirebaseAuth.getInstance().currentUser?.uid ?: return
    FirebaseDatabase.getInstance()
        .getReference("fcm_tokens/$uid/token")
        .setValue(token)
}
```

Chỉ thiết bị cuối cùng đăng nhập nhận push (1 user = 1 token).

### 5.3. User chưa đăng nhập Firebase Auth (walk-in)

Bệnh nhân walk-in (bác sĩ thêm trực tiếp) không có Firebase Auth account → không có FCM token → Django skip push nhưng vẫn ghi notification vào RTDB.

Nếu sau này bệnh nhân tạo account và đăng nhập app → có thể đọc notifications cũ (nếu `patientID` được dùng làm key).

### 5.4. Nhiều notifications cho cùng 1 appointment

Cờ `notifyFlags.almostSent` trên appointment đảm bảo chỉ gửi **1 lần** cho mỗi appointment. Nếu bệnh nhân bị đẩy lùi vị trí (do priority) rồi quay lại vị trí 4, sẽ KHÔNG gửi lại.

---

## 6. Checklist tích hợp

### Phía App Android

- [ ] Thêm dependency: `firebase-messaging-ktx`
- [ ] Tạo `MyFirebaseMessagingService` (handle `onMessageReceived` + `onNewToken`)
- [ ] Đăng ký service trong `AndroidManifest.xml`
- [ ] Gọi `registerFcmToken()` sau login thành công
- [ ] Khi đặt lịch: ghi `userID = FirebaseAuth.currentUser.uid` vào appointment
- [ ] Listen `notifications/{uid}` để hiển thị danh sách thông báo
- [ ] Update `read = true` khi user tap thông báo
- [ ] Tạo NotificationChannel "queue_notifications" (Android 8+)

### Phía Web Django (ĐÃ HOÀN THÀNH ✅)

- [x] `services/queue_notifications.py` — logic gửi notification
- [x] Đọc `fcm_tokens/{userID}/token` để gửi push
- [x] Ghi `notifications/{userID}/{pushKey}` để app đọc
- [x] Ghi `notifyFlags.almostSent` chống gửi trùng
- [x] Handle `UnregisteredError` → xóa token cũ
- [x] Hook vào `examine_view` (sau khám xong)
- [x] Hook vào `scan_view` (sau check-in)
- [x] Hook vào `create_appointment_view` (walk-in)

### Firebase Console

- [ ] Cập nhật Security Rules (mục 4)
- [ ] Verify node `fcm_tokens/` và `notifications/` tồn tại

---

## 7. Test thủ công

### Bước 1: Verify token lưu đúng

1. App đăng nhập → kiểm tra Firebase Console → RTDB → `fcm_tokens/{uid}`
2. Phải thấy: `{ token: "...", platform: "android", updatedAt: ... }`

### Bước 2: Verify notification ghi đúng

1. Tạo 4 bệnh nhân walk-in trên web (hoặc 4 check-in qua IoT)
2. Bác sĩ khám xong bệnh nhân đầu tiên
3. Kiểm tra Firebase Console → `notifications/{userID_của_bệnh_nhân_thứ_4}`
4. Phải thấy node mới với `type: "queue_almost"`

### Bước 3: Verify push nhận được

1. Đảm bảo bước 1 + 2 OK
2. App phải nhận system notification khi bác sĩ khám xong
3. Mở app → tab thông báo → thấy "Sắp đến lượt khám"

### Debug nếu không nhận push

| Triệu chứng | Nguyên nhân | Fix |
|---|---|---|
| Không có node trong `fcm_tokens/` | App chưa gọi `registerFcmToken()` | Gọi sau login |
| Có token nhưng không nhận push | Token hết hạn | Gọi lại `registerFcmToken()` |
| Console log: "No FCM token for..." | `userID` không khớp | Kiểm tra appointment.userID == auth.uid |
| Console log: "Token invalid..." | App bị gỡ/cài lại | Đăng nhập lại trên app |
| Có notification trong RTDB nhưng app không hiện | App chưa listen `notifications/{uid}` | Thêm ChildEventListener |

---

## 8. Sơ đồ tổng hợp

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FIREBASE RTDB                                  │
│                                                                      │
│  fcm_tokens/                    notifications/                       │
│    {uid}/                         {uid}/                             │
│      token: "fGx..."               {pushKey}/                       │
│      platform: "android"              type: "queue_almost"           │
│      updatedAt: 17162...              title: "Sắp đến lượt"         │
│                                       body: "Còn 3 người..."        │
│                                       read: false                    │
│                                                                      │
│  appointment_new/                                                    │
│    {doctor}/{date}/{apt}/                                            │
│      ...                                                             │
│      notifyFlags/                                                    │
│        almostSent: true                                              │
│        almostSentAt: 17162...                                        │
└─────────────────────────────────────────────────────────────────────┘
         ↑ ghi token              ↑ ghi notif        ↑ đọc token
         │                        │                  │
    ┌────┴────┐              ┌────┴──────────────────┴────┐
    │   APP   │              │          DJANGO             │
    │ Android │              │  (queue_notifications.py)   │
    │         │←── FCM push ─│                             │
    │         │              │  Trigger: examine_view      │
    │         │── listen ───→│           scan_view         │
    │         │  notifications│           create_appt      │
    └─────────┘              └─────────────────────────────┘
```
