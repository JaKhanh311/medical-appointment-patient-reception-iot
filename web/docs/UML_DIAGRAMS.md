# Sơ đồ UML — Hệ thống OPDFlow

Tài liệu này chứa các sơ đồ Use Case, Sequence và Activity cho các chức năng chính của hệ thống, gồm 2 thành phần:

1. **doctor_portal_project** — Web portal cho bác sĩ và admin (Django)
2. **IoT (kiosk QR scanner)** — Thiết bị quét mã QR check-in tại phòng khám

## Cách render sơ đồ

- **Online**: Copy nội dung khối `@startuml ... @enduml` vào https://www.plantuml.com/plantuml/
- **VS Code**: Cài extension "PlantUML" → mở file → Alt+D
- **CLI**: `plantuml diagram.puml`

---

## 1. SƠ ĐỒ USE CASE

### 1.1. Use Case tổng quan toàn hệ thống

```plantuml
@startuml UseCase_Overall
left to right direction
skinparam packageStyle rectangle
skinparam actorStyle awesome

actor "Bệnh nhân" as Patient
actor "Bác sĩ" as Doctor
actor "Quản trị viên" as Admin
actor "Thiết bị IoT\n(QR Scanner)" as IoT

rectangle "Hệ thống OPDFlow" {
    package "Ứng dụng Android" {
        usecase "Đặt lịch khám" as UC_Book
        usecase "Xem lịch hẹn" as UC_ViewAppt
        usecase "Nhận thông báo\nsắp tới lượt" as UC_Notify
        usecase "Quét QR check-in" as UC_QRScan
    }

    package "Web Portal Bác sĩ" {
        usecase "Đăng nhập" as UC_DoctorLogin
        usecase "Xem hàng đợi\nbệnh nhân" as UC_Queue
        usecase "Gọi bệnh nhân\n(phát âm)" as UC_Call
        usecase "Khám bệnh và\nlưu hồ sơ" as UC_Examine
        usecase "Thêm bệnh nhân\nwalk-in" as UC_WalkIn
        usecase "Đánh dấu\nkhông đến" as UC_NoShow
        usecase "Đánh dấu ưu tiên" as UC_Priority
        usecase "Xem thống kê" as UC_Stats
    }

    package "Web Portal Admin" {
        usecase "Quản lý bác sĩ" as UC_ManageDoctor
        usecase "Đổi mật khẩu\nbác sĩ" as UC_ResetPwd
        usecase "Xuất dữ liệu\nFHIR R4" as UC_FHIR
    }

    package "Kiosk IoT" {
        usecase "Quét mã QR" as UC_Scan
        usecase "Xác thực ngày\nlịch hẹn" as UC_ValidateDate
        usecase "Cập nhật\ntrạng thái đến" as UC_UpdateStatus
        usecase "Tạo queue token" as UC_CreateToken
    }
}

Patient --> UC_Book
Patient --> UC_ViewAppt
Patient --> UC_Notify
Patient --> UC_QRScan

Doctor --> UC_DoctorLogin
Doctor --> UC_Queue
Doctor --> UC_Call
Doctor --> UC_Examine
Doctor --> UC_WalkIn
Doctor --> UC_NoShow
Doctor --> UC_Priority
Doctor --> UC_Stats

Admin --> UC_ManageDoctor
Admin --> UC_ResetPwd
Admin --> UC_FHIR

IoT --> UC_Scan
UC_Scan --> UC_ValidateDate : <<include>>
UC_ValidateDate --> UC_UpdateStatus : <<include>>
UC_UpdateStatus --> UC_CreateToken : <<include>>

UC_Examine ..> UC_Notify : <<extend>>\ngửi thông báo\ncho người\nsắp tới lượt
@enduml
```

### 1.2. Use Case của Bác sĩ

```plantuml
@startuml UseCase_Doctor
left to right direction
skinparam actorStyle awesome

actor "Bác sĩ" as Doctor

rectangle "Doctor Portal" {
    usecase "Đăng nhập\n(email + password)" as Login
    usecase "Xem dashboard\nhàng đợi hôm nay" as Dashboard
    usecase "Lọc theo buổi\nsáng/chiều" as Filter
    usecase "Tìm kiếm\nbệnh nhân" as Search
    usecase "Xem chi tiết\nbệnh nhân" as ViewDetail
    usecase "Gọi bệnh nhân\n(phát âm TTS)" as Announce
    usecase "Khám ngay" as ExamineNow
    usecase "Lưu kết quả khám\n(chuẩn đoán + đơn thuốc)" as SaveExam
    usecase "Thêm bệnh nhân\nwalk-in" as AddWalkIn
    usecase "Đánh dấu ưu tiên" as MarkPriority
    usecase "Đánh dấu\nkhông đến" as MarkNoShow
    usecase "Xem lịch sử khám" as History
    usecase "Xem thống kê" as Statistics
    usecase "Mở phòng chờ\n(màn hình bệnh nhân)" as PatientDisplay
}

Doctor --> Login
Doctor --> Dashboard
Dashboard ..> Filter : <<include>>
Dashboard ..> Search : <<include>>
Dashboard ..> ViewDetail : <<extend>>
Dashboard ..> Announce : <<extend>>
Dashboard ..> ExamineNow : <<extend>>
Dashboard ..> AddWalkIn : <<extend>>
Dashboard ..> MarkPriority : <<extend>>
Dashboard ..> MarkNoShow : <<extend>>
Dashboard ..> PatientDisplay : <<extend>>

ExamineNow ..> SaveExam : <<include>>
Doctor --> History
Doctor --> Statistics
@enduml
```

### 1.3. Use Case của Quản trị viên

```plantuml
@startuml UseCase_Admin
left to right direction
skinparam actorStyle awesome

actor "Quản trị viên" as Admin

rectangle "Admin Portal" {
    usecase "Đăng nhập admin" as AdminLogin
    usecase "Xem danh sách\nbác sĩ" as ListDoctors
    usecase "Tìm kiếm bác sĩ" as SearchDoctor
    usecase "Thêm bác sĩ mới" as AddDoctor
    usecase "Sửa thông tin\nbác sĩ" as EditDoctor
    usecase "Đổi mật khẩu\nbác sĩ" as ResetPassword
    usecase "Xem lịch sử khám\ncủa bác sĩ" as ViewDoctorHistory
    usecase "Xuất dữ liệu\nFHIR R4" as ExportFHIR
    usecase "Xem trước\ndữ liệu xuất" as PreviewFHIR
    usecase "Tải file JSON\nFHIR Bundle" as DownloadFHIR
}

Admin --> AdminLogin
Admin --> ListDoctors
ListDoctors ..> SearchDoctor : <<include>>
Admin --> AddDoctor
Admin --> EditDoctor
Admin --> ResetPassword
Admin --> ViewDoctorHistory
Admin --> ExportFHIR
ExportFHIR ..> PreviewFHIR : <<include>>
ExportFHIR ..> DownloadFHIR : <<include>>
@enduml
```

### 1.4. Use Case của Thiết bị IoT

```plantuml
@startuml UseCase_IoT
left to right direction
skinparam actorStyle awesome

actor "Bệnh nhân" as Patient
actor "Firebase RTDB" as Firebase

rectangle "Kiosk IoT" {
    usecase "Khởi động camera" as StartCamera
    usecase "Cấu hình ROI\n(vùng quét)" as ConfigROI
    usecase "Quét và giải mã\nQR code" as ScanQR
    usecase "Giải mã payload\n(AES decrypt)" as Decrypt
    usecase "Tra cứu lịch hẹn" as LookupAppt
    usecase "Kiểm tra trạng thái\n(đã hủy/quá hạn)" as CheckStatus
    usecase "Kiểm tra ngày hẹn" as CheckDate
    usecase "Cập nhật\nstatus = 'Đã đến'" as UpdateArrived
    usecase "Tạo token hàng đợi" as CreateQueueToken
    usecase "Phát thanh\nchào mừng" as PlayWelcome
    usecase "Hiển thị thông báo\nthành công/lỗi" as ShowResult
}

Patient --> ScanQR
ScanQR ..> Decrypt : <<include>>
Decrypt ..> LookupAppt : <<include>>
LookupAppt ..> CheckStatus : <<include>>
CheckStatus ..> CheckDate : <<include>>
CheckDate ..> UpdateArrived : <<extend>>\n[ngày hợp lệ]
UpdateArrived ..> CreateQueueToken : <<include>>
ScanQR ..> ShowResult : <<include>>
ScanQR ..> PlayWelcome : <<extend>>\n[thành công]

LookupAppt --> Firebase
UpdateArrived --> Firebase
CreateQueueToken --> Firebase
@enduml
```

---

## 2. SƠ ĐỒ SEQUENCE

### 2.1. Bác sĩ đăng nhập

```plantuml
@startuml Sequence_DoctorLogin
actor "Bác sĩ" as Doctor
participant "Trình duyệt" as Browser
participant "Django Server" as Django
database "Firebase RTDB" as RTDB
participant "Firebase Auth" as Auth

Doctor -> Browser: Nhập email + password
Browser -> Django: POST /login/\n{username, password}

activate Django
Django -> RTDB: get('doctors/{id}')
RTDB --> Django: doctor profile
Django -> Auth: signInWithEmailAndPassword()
Auth --> Django: ID token + UID

alt Đăng nhập thành công
    Django -> Django: Tạo session\n(doctor_id, name, specialty)
    Django --> Browser: Redirect /appointments/dashboard/
    Browser -> Django: GET /dashboard/
    Django -> RTDB: get('appointment_new/{doctor_id}/{date}')
    RTDB --> Django: appointments list
    Django --> Browser: Render dashboard.html
    Browser --> Doctor: Hiển thị dashboard
else Sai mật khẩu
    Auth --> Django: 401 Unauthorized
    Django --> Browser: messages.error
    Browser --> Doctor: Hiển thị lỗi
end
deactivate Django
@enduml
```

### 2.2. Bệnh nhân check-in qua thiết bị IoT

```plantuml
@startuml Sequence_QRCheckIn
actor "Bệnh nhân" as Patient
participant "Kiosk IoT\n(qr_scan.py)" as Kiosk
participant "Camera" as Camera
participant "Firebase RTDB" as RTDB
participant "Speaker (TTS)" as Speaker

Patient -> Kiosk: Đưa mã QR vào camera
activate Kiosk
Kiosk -> Camera: Đọc frame
Camera --> Kiosk: image frame
Kiosk -> Kiosk: Decode QR (cv2.QRCodeDetector)
Kiosk -> Kiosk: AES decrypt → appointment_id

Kiosk -> RTDB: get('appointment_new/.../{apt_id}')
RTDB --> Kiosk: appointment data

alt Status = "completed"
    Kiosk --> Patient: "Đã hoàn tất khám,\ncảm ơn quý khách"
else Status = "Đã đến" (re-scan)
    Kiosk --> Patient: Hiển thị giờ check-in\n+ số thứ tự
else Status = "cancelled" / "no_show"
    Kiosk --> Patient: "Lịch đã hủy/quá hạn"
else Ngày hẹn ≠ hôm nay
    Kiosk -> Kiosk: Validate date
    Kiosk --> Patient: "Chưa đến ngày khám\n(DD/MM/YYYY)"
else Status = "scheduled" + ngày hợp lệ
    Kiosk -> RTDB: get('patients/{patient_id}')
    RTDB --> Kiosk: patient data
    Kiosk -> RTDB: get('queues/{doctor_id}/{date}')
    RTDB --> Kiosk: queue tokens
    Kiosk -> Kiosk: Tính position tiếp theo

    Kiosk -> RTDB: update('appointment_new/.../{apt_id}',\n{status: "Đã đến", checkedInAt})
    Kiosk -> RTDB: push('queues/{doctor_id}/{date}',\n{appointmentID, position, ...})
    RTDB --> Kiosk: OK

    Kiosk -> Speaker: Phát "Chào mừng {name}"
    Speaker --> Patient: 🔊 Audio
    Kiosk --> Patient: Hiển thị STT + giờ check-in
end
deactivate Kiosk
@enduml
```

### 2.3. Bác sĩ gọi bệnh nhân và khám bệnh

```plantuml
@startuml Sequence_ExamineFlow
actor "Bác sĩ" as Doctor
participant "Dashboard\n(JS poll)" as Dashboard
participant "Django" as Django
database "Firebase RTDB" as RTDB
participant "Edge TTS" as TTS
participant "Speaker" as Speaker

== Polling realtime ==
Dashboard -> Django: GET /dashboard/poll/?date=...&snapshot_key=...
Django -> RTDB: get('appointment_new/{doctor_id}/{date}')
Django -> RTDB: get('queues/{doctor_id}/{date}')
RTDB --> Django: appointments + queue tokens
Django --> Dashboard: JSON (changed: true, appointments[])
Dashboard --> Doctor: Render danh sách

== Gọi bệnh nhân ==
Doctor -> Dashboard: Click "Phát âm" 📢
Dashboard -> Django: POST /dashboard/tts-prefetch/\n{appointment_id, name}
Django -> TTS: Synthesize "Mời bệnh nhân X\nvào phòng khám"
TTS --> Django: file mp3
Django --> Dashboard: { call_url: "/static/.../call.mp3" }
Dashboard -> Speaker: <audio> play
Speaker -> Doctor: 🔊

== Khám bệnh ==
Doctor -> Dashboard: Click "Khám ngay" 🩺
Dashboard -> Django: GET /examine/{appointment_id}/
Django -> RTDB: get('appointment_new/.../{apt_id}')
Django -> RTDB: get('patients/{patient_id}')
RTDB --> Django: full patient + appointment data
Django --> Doctor: examine_views.html (form)

Doctor -> Doctor: Điền chuẩn đoán,\ntriệu chứng, đơn thuốc
Doctor -> Django: POST /examine/{apt_id}/\n{symptoms, diagnosis, prescription[]}

activate Django
Django -> RTDB: update('appointment_new/.../{apt_id}',\n{status: "completed"})
Django -> RTDB: push('medicalRecords/{patient_id}',\n{symptoms, diagnosis, ...})
Django -> RTDB: update('queues/.../{token}',\n{status: "complete"})

== Trigger thông báo ==
Django -> Django: notify_queue_advance()
Django -> RTDB: get('appointment_new/{doctor_id}/{date}')
Django -> Django: Tìm bệnh nhân ở vị trí 4
Django -> RTDB: push('notifications/{userID}',\n{type: "queue_almost"})
Django -> Django: Send FCM push (firebase-admin)
Django -> RTDB: update('appointment_new/.../{apt_4}',\n{notifications.almostSent: true})

Django -> Django: invalidate_dashboard_cache()
Django --> Doctor: Redirect /dashboard/
deactivate Django
@enduml
```

### 2.4. Thông báo "Sắp tới lượt" tới App Android

```plantuml
@startuml Sequence_QueueNotification
participant "Django\n(notify_queue_advance)" as Django
database "Firebase RTDB" as RTDB
participant "Firebase Cloud\nMessaging (FCM)" as FCM
participant "App Android" as App
actor "Bệnh nhân" as Patient

Django -> RTDB: Đọc waiting appointments\n(sorted by arrival time)
RTDB --> Django: list

Django -> Django: Tìm bệnh nhân ở vị trí 4\n(còn 3 người trước)

alt almostSent == true
    Django -> Django: Skip (đã gửi rồi)
else almostSent == false
    Django -> RTDB: get('patients/{pid}/userID')
    RTDB --> Django: user_id

    Django -> RTDB: push('notifications/{user_id}',\n{type, title, body, ...})
    Django -> RTDB: get('fcm_tokens/{user_id}/token')
    RTDB --> Django: FCM token

    Django -> FCM: messaging.send(token, payload)
    FCM --> App: 📱 Push notification
    App --> Patient: Hiển thị notification\n"Sắp đến lượt khám"

    Django -> RTDB: update('appointment_new/.../{apt_id}',\n{notifications.almostSent: true})
end

== Khi user mở app ==
Patient -> App: Tap notification
App -> RTDB: listen('notifications/{user_id}')
RTDB --> App: realtime data
App --> Patient: Hiển thị danh sách thông báo
Patient -> App: Tap để đọc
App -> RTDB: update('notifications/.../read', true)
@enduml
```

### 2.5. Bác sĩ thêm bệnh nhân walk-in

```plantuml
@startuml Sequence_WalkIn
actor "Bác sĩ" as Doctor
participant "Dashboard" as Dashboard
participant "Django" as Django
database "Firebase RTDB" as RTDB

Doctor -> Dashboard: Click "Thêm bệnh nhân"
Dashboard -> Django: GET /appointments/add-patient/
Django --> Doctor: Form tìm/tạo bệnh nhân

Doctor -> Django: POST tạo bệnh nhân mới\nhoặc chọn bệnh nhân có sẵn
Django -> RTDB: push('patients/', {name, phone, ...})
RTDB --> Django: patient_id

Django --> Doctor: Redirect /appointments/create/\n?patient_id=...
Doctor -> Doctor: Chọn buổi sáng/chiều,\nbệnh viện, lý do khám
Doctor -> Django: POST /appointments/create/

activate Django
Django -> RTDB: get('doctors/{doctor_id}')
Django -> RTDB: get('hospitals')
Django -> RTDB: push('appointment_new/{doctor_id}/{date}/',\n{patientID, doctorID, session,\nstatus: "Đã đến"})
RTDB --> Django: appointment_id

Django -> RTDB: update('appointment_new/.../{apt_id}',\n{arrivalTime: now})
Django -> RTDB: get('queues/{doctor_id}/{date}')
RTDB --> Django: existing tokens
Django -> Django: position = count + 1
Django -> RTDB: push('queues/{doctor_id}/{date}/',\n{appointmentID, position, status: "waiting"})

Django -> Django: invalidate_dashboard_cache()
Django -> Django: notify_queue_advance()
Django --> Doctor: Redirect /dashboard/?date=...
deactivate Django

Doctor -> Dashboard: Thấy bệnh nhân mới\ntrong danh sách chờ
@enduml
```

### 2.6. Admin xuất dữ liệu FHIR R4

```plantuml
@startuml Sequence_FHIRExport
actor "Admin" as Admin
participant "Browser" as Browser
participant "Django\n(views_fhir_export)" as Django
participant "export_fhir.py\nconvert_to_fhir()" as Converter
database "Firebase RTDB" as RTDB

Admin -> Browser: Click "Xuất FHIR R4"
Browser -> Django: GET /admin-portal/fhir-export/
Django --> Browser: admin_fhir_export.html

Browser -> Django: POST /fhir-export/summary/
Django -> RTDB: get('hospitals'), get('specialties'),\nget('doctors'), get('patients'),\nget('appointment_new'), get('medicalRecords')
RTDB --> Django: counts
Django --> Browser: JSON (counts dict)
Browser --> Admin: Hiển thị thống kê

Admin -> Browser: Click "Tải xuống FHIR Bundle"
Browser -> Django: POST /fhir-export/execute/?format=download

activate Django
Django -> RTDB: db.get() (toàn bộ database)
RTDB --> Django: full snapshot

Django -> Converter: convert_to_fhir(db_data)
activate Converter
Converter -> Converter: Map hospitals → Organization
Converter -> Converter: Map specialties → HealthcareService
Converter -> Converter: Map doctors → Practitioner +\nPractitionerRole
Converter -> Converter: Map patients → Patient +\nObservation + AllergyIntolerance
Converter -> Converter: Map appointments → Appointment
Converter -> Converter: Map medical records → Encounter +\nCondition + MedicationRequest
Converter -> Converter: Wrap thành FHIR Bundle
Converter --> Django: bundle JSON
deactivate Converter

Django --> Browser: HTTP 200\nContent-Type: application/fhir+json\nContent-Disposition: attachment
Browser --> Admin: 💾 fhir_r4_export_YYYYMMDD.json
deactivate Django
@enduml
```

---

## 3. SƠ ĐỒ ACTIVITY

### 3.1. Luồng đặt lịch + check-in + khám bệnh tổng quát

```plantuml
@startuml Activity_OverallFlow
|Bệnh nhân|
start
:Đặt lịch khám trên app Android;
:Lưu vào Firebase RTDB\n(appointment_new, status="scheduled");

:Đến ngày khám;
:Đến phòng khám;

|Kiosk IoT|
:Quét mã QR của bệnh nhân;
:AES decrypt → appointment_id;
:Truy vấn appointment từ RTDB;

if (Appointment có tồn tại?) then (no)
    :Hiển thị "Mã QR không hợp lệ";
    stop
else (yes)
endif

if (Status?) then (completed)
    :Hiển thị "Đã hoàn tất";
    stop
elseif (cancelled / no_show) then
    :Hiển thị "Lịch đã hủy/quá hạn";
    stop
elseif (Đã đến — re-scan) then
    :Hiển thị giờ check-in + STT;
    stop
endif

if (Ngày hẹn = hôm nay?) then (no)
    :Hiển thị "Chưa đến ngày khám\n(DD/MM/YYYY)" hoặc "Đã quá hạn";
    stop
else (yes)
endif

:Cập nhật status = "Đã đến";
:Tạo queue token với position;
:Phát thanh "Chào mừng {name}";
:Hiển thị STT + giờ check-in;

|Bác sĩ|
:Mở dashboard portal;
:Thấy bệnh nhân trong danh sách chờ\n(realtime poll mỗi 5s);

repeat
    if (Có bệnh nhân ưu tiên?) then (yes)
        :Đánh dấu ưu tiên\n(lên đầu hàng đợi);
    endif

    :Click "Phát âm" gọi bệnh nhân;
    note right: TTS "Mời bệnh nhân X\nvào phòng khám"

    if (Bệnh nhân vào phòng?) then (yes)
        :Click "Khám ngay";
        :Khám bệnh, ghi chuẩn đoán,\nkê đơn thuốc;
        :Lưu kết quả khám\n(status = "completed");

        |Hệ thống|
        :Trigger notify_queue_advance();
        :Tìm bệnh nhân ở vị trí 4;
        if (Chưa gửi thông báo?) then (yes)
            :Gửi FCM push\n"Còn 3 người phía trước";

            |Bệnh nhân|
            :Nhận thông báo trên app;
        endif

    else (no)
        |Bác sĩ|
        :Click "Bỏ qua / Không đến";
        :Mark status = "no_show";
    endif
repeat while (Còn bệnh nhân chờ?) is (yes)
-> no;

stop
@enduml
```

### 3.2. Luồng kiểm tra ngày check-in tại Kiosk IoT

```plantuml
@startuml Activity_KioskValidation
start
:Camera đọc frame;
:Detect QR code;

if (Có QR data?) then (no)
    stop
else (yes)
endif

:AES Decrypt payload;

if (Decrypt thành công?) then (no)
    :Hiển thị "Lỗi giải mã QR";
    stop
else (yes)
endif

:Lookup appointment trên RTDB;

if (Appointment tồn tại?) then (no)
    :Hiển thị "Không tìm thấy lịch khám";
    stop
else (yes)
endif

:Lấy appt.status;

switch (status?)
case (completed)
    :"Đã hoàn tất khám";
    stop
case (cancelled / no_show)
    :"Lịch đã hủy/quá hạn";
    stop
case (Đã đến / arrived)
    :Hiển thị giờ check-in + STT\n(safe re-scan);
    stop
case (scheduled)
    :Tiếp tục validation ngày;
endswitch

:Lấy appt.date / appointmentDate;
:Normalize sang YYYY-MM-DD;

if (Ngày hợp lệ?) then (no)
    :Bỏ qua check ngày,\ncho phép check-in;
else (yes)
    if (Ngày hẹn > hôm nay?) then (yes)
        :"Chưa đến ngày khám\nLịch hẹn vào DD/MM/YYYY";
        stop
    endif
    if (Ngày hẹn < hôm nay?) then (yes)
        :"Lịch khám đã quá hạn\nĐặt lịch mới";
        stop
    endif
endif

:Lấy patientID từ appointment;
:Get patient data từ RTDB;
:Get current queue tokens;
:Tính next position;

:Update appointment\n{status: "Đã đến", checkedInAt};
:Push queue token mới\n{appointmentID, position};

:Phát thanh "Chào mừng {name}";
:Hiển thị STT + giờ check-in;
stop
@enduml
```

### 3.3. Luồng tự động đánh dấu no-show

```plantuml
@startuml Activity_AutoNoShow
|Cron Job (Task Scheduler)|
start
:Trigger lúc 12:05 (sau buổi sáng)\nhoặc 17:05 (sau buổi chiều)\nhoặc thủ công bằng `auto_no_show`;

|Django Management Command|
:Đọc tham số --date, --session, --doctor;

if (--session được set?) then (yes)
    :sessions_to_process = [session];
else (no)
    if (Hour >= 12?) then
        :Add "morning";
    endif
    if (Hour >= 17?) then
        :Add "afternoon";
    endif

    if (date < today?) then (yes)
        :sessions = ["morning", "afternoon"];
    endif
endif

if (Có session nào cần xử lý?) then (no)
    :Print "Chưa đến giờ đóng buổi";
    stop
endif

if (--doctor được set?) then (yes)
    :doctor_ids = [doctor];
else (no)
    :doctor_ids = get_all_doctors();
endif

repeat :Với mỗi doctor_id;
    repeat :Với mỗi session;
        :Query appointment_new/{doctor}/{date};

        repeat :Với mỗi appointment;
            if (status == "scheduled"?) then (no)
                ->skip;
            else (yes)
                if (session khớp?) then (yes)
                    :Update status = "no_show";
                    :noShowReason = "session_closed";
                    :noShowAt = now;
                    :counter += 1;
                endif
            endif
        repeat while (còn appointment) is (yes)
        ->no;
    repeat while (còn session) is (yes)
    ->no;
repeat while (còn doctor) is (yes)
->no;

:Print tổng số đã chuyển no_show;
stop
@enduml
```

### 3.4. Luồng admin tạo bác sĩ mới

```plantuml
@startuml Activity_AdminCreateDoctor
|Admin|
start
:Truy cập trang "Thêm bác sĩ";
:Điền form:\n- Họ tên\n- Email (= username)\n- Ngày sinh (= ddmmyyyy mật khẩu)\n- Chuyên khoa\n- Bệnh viện\n- Hồ sơ chi tiết;
:Submit form;

|Django|
:Nhận POST request;
:Validate email và ngày sinh;

if (Email hợp lệ?) then (no)
    :Hiển thị lỗi;
    stop
endif

if (Ngày sinh hợp lệ?) then (no)
    :Hiển thị lỗi;
    stop
endif

:Convert ngày sinh → password ddmmyyyy;
:username = email;

:Tạo doctor profile trên RTDB\ndoctors/{doctor_id};
:Tạo Firebase Auth account\n(email + password);

if (Email đã tồn tại trên Auth?) then (yes)
    :Link với account hiện có;
    :Update password mới;
else (no)
    :Tạo account mới;
endif

:Cập nhật doctor.userID = uid;
:Tạo entry users/{uid}\n(role: doctor);
:Xóa field password plaintext\nkhỏi RTDB;

:Hiển thị message thành công\n+ thông tin tài khoản;
:Redirect đến trang sửa bác sĩ;

|Admin|
:Có thể chỉnh sửa thêm thông tin;
stop
@enduml
```

### 3.5. Luồng polling realtime của Dashboard

```plantuml
@startuml Activity_DashboardPolling
|Browser (JavaScript)|
start
:Page load → DOMContentLoaded;
:Đọc dataset (selectedDate, pollUrl,\ninitialSnapshotKey);
:poll() lần đầu;

repeat
    if (document.hidden?) then (yes)
        :Pause polling;
        :Đợi visibilitychange;
    else (no)
        :Fetch /dashboard/poll/?date=...&snapshot_key=...;
    endif

    |Django|
    :Nhận GET request;
    :Check cache (version_key);

    if (Cache hit + key khớp?) then (yes)
        :Return changed: false (lightweight);
    else (no)
        if (Cache hit nhưng key khác?) then (yes)
            :Return cached payload;
        else (no)
            :Build context từ Firebase\n(_get_dashboard_context_cached);
            :Tính snapshot_key (sha1);
            :Cache version + snapshot;
            :Return full payload (changed: true);
        endif
    endif

    |Browser|
    if (response.changed == false?) then (yes)
        :setLive(true);\nKhông update DOM;
    else (no)
        :updateStats();
        :updateList(appointments);

        if (Order key thay đổi?) then (yes)
            :Reorder DOM;
        endif

        if (Status hoặc priority thay đổi?) then (yes)
            :Flash row animation;
            :showToast("Lịch đã cập nhật");
        endif

        :setLive(true);
    endif
repeat while (5 giây) is (yes)
->stop;

stop
@enduml
```

---

## 4. CÁCH RENDER SƠ ĐỒ

### 4.1. Online (nhanh nhất)

1. Truy cập https://www.plantuml.com/plantuml/uml
2. Copy nội dung từ `@startuml` đến `@enduml`
3. Paste vào textarea → enter
4. Right-click ảnh → Save image as PNG/SVG

### 4.2. VS Code

1. Cài extension **"PlantUML"** (jebbs.plantuml)
2. Tạo file `.puml` với nội dung
3. Alt+D để preview
4. File → Export Current Diagram → chọn PNG/SVG

### 4.3. CLI

```bash
# Cài plantuml (cần Java)
# Tải: https://plantuml.com/download

# Render
java -jar plantuml.jar diagram.puml
# Sinh ra diagram.png
```

### 4.4. Docker

```bash
docker run -v $(pwd):/data plantuml/plantuml -tpng *.puml
```

---

## 5. GỢI Ý CHO BÁO CÁO

**Thứ tự đề xuất chèn vào báo cáo:**

| Chương | Sơ đồ |
|--------|-------|
| Phân tích yêu cầu | Use Case tổng quan (1.1) |
| Đặc tả chức năng | Use Case từng actor (1.2-1.4) |
| Thiết kế chi tiết — Bác sĩ | Sequence 2.1, 2.3, 2.5 + Activity 3.1, 3.5 |
| Thiết kế chi tiết — IoT | Sequence 2.2 + Activity 3.2 |
| Thiết kế chi tiết — Notification | Sequence 2.4 |
| Thiết kế chi tiết — Admin | Sequence 2.6 + Activity 3.4 |
| Thiết kế chi tiết — Background | Activity 3.3 (auto no-show) |

**Style tip:**
- Đặt mỗi sơ đồ trong 1 figure riêng, đánh số (Hình 4.1, 4.2, ...)
- Mỗi sơ đồ kèm 1-2 dòng caption mô tả
- Render PNG với `dpi=300` cho in ấn rõ nét
