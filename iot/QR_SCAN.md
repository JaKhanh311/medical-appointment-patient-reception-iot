# qr_scan.py — Tài liệu kỹ thuật

## Tổng quan

`qr_scan.py` là module lõi của hệ thống, xử lý toàn bộ vòng đời quét QR: mở camera → decode QR → giải mã AES-GCM → cập nhật Firebase → hiển thị kết quả. Tích hợp thêm UI cấu hình camera trực quan qua OpenCV.

---

## Phụ thuộc

| Module | Mục đích |
|--------|----------|
| `cv2` (OpenCV) | Capture camera, xử lý ảnh, hiển thị UI |
| `pyzbar` | Decode QR code từ ảnh |
| `numpy` | Xử lý ma trận ảnh |
| `Pillow` (PIL) | Vẽ text Unicode (tiếng Việt) lên frame |
| `cryptography` | Giải mã AES-256-GCM |
| `python-dotenv` | Load biến môi trường từ `.env` |
| `threading` | `camera_lock` để tránh xung đột mở/đóng camera |
| `firebase_conn` | Đọc/ghi dữ liệu Firebase Realtime DB |

---

## Hằng số & Cấu hình

### File cấu hình

```python
CONFIG_FILE = "camera_config.json"
```

### `CONFIG_CONTROL_SPECS`

10 thông số điều chỉnh trong UI cấu hình camera:

| Key | Label | Min | Max | Step |
|-----|-------|-----|-----|------|
| `auto_camera` | Auto Camera | 0 | 1 | 1 |
| `brightness` | Brightness | 0 | 100 | 1 |
| `contrast` | Contrast | 0 | 300 | 5 |
| `exposure` | Exposure | 0 | 20 | 1 |
| `gain` | Gain | 0 | 100 | 1 |
| `focus` | Focus | 0 | 255 | 5 |
| `sharpness` | Sharpness | 0 | 100 | 1 |
| `saturation` | Saturation | 0 | 200 | 2 |
| `roi_width` | ROI Width % | 10 | 100 | 1 |
| `roi_height` | ROI Height % | 10 | 100 | 1 |

### `CAMERA_CONFIG_UI_THEME`

```python
{
    "dark":  { "canvas_bg": "#0A0A0A", "bar_fill": "#16A34A", ... },
    "light": { "canvas_bg": "#FFFFFF", "bar_fill": "#374151", ... }
}
```

### `KEY_REPEAT_INTERVAL = 0.09`

Thời gian chờ tối thiểu (giây) giữa hai lần nhấn giữ phím điều hướng.

---

## Cấu trúc camera_config.json

```json
{
    "auto_camera": true,
    "brightness": 80,
    "contrast": 1.15,
    "gain": 15,
    "exposure": -1,
    "focus": 20,
    "sharpness": 70,
    "saturation": 200,
    "roi_scale": 0.7,
    "roi_height_scale": 0.7,
    "camera_width": 1280,
    "camera_height": 720,
    "camera_fps": 30,
    "custom_message": "Mã lịch hẹn đã bị hủy hoặc quá hạn..."
}
```

> **Lưu ý:** `contrast` lưu dưới dạng float `[0.0, 3.0]` nhưng UI hiển thị nhân 100 (0–300). `exposure` lưu giá trị thực (`-1`), UI hiển thị +10 (offset).

---

## Nhóm hàm

### 1. Quản lý cấu hình camera

```python
def _load_camera_config() -> dict
```
Đọc `camera_config.json`. Trả về default config nếu file không tồn tại hoặc lỗi.

```python
def _save_camera_config(config: dict) -> None
```
Ghi config ra `camera_config.json` dưới dạng JSON indent=2.

```python
def _reset_camera_config() -> dict
```
Ghi lại default config và trả về. Gọi khi người dùng nhấn "Reset".

```python
def _get_default_camera_config() -> dict
```
Trả về default config (nội bộ). `camera_index` mặc định: `"0"` (Windows) hoặc `"/dev/video0"` (Linux).

### 2. Chuyển đổi trạng thái UI ↔ config

```python
def _build_camera_control_state(config: dict) -> dict
```
Chuyển config float/bool → int cho UI slider. Ví dụ: `contrast: 1.15` → `contrast: 115`.

```python
def _control_state_to_config_values(state: dict) -> dict
```
Ngược lại: chuyển int UI → float/bool config. Ví dụ: `contrast: 115` → `contrast: 1.15`.

```python
def _format_camera_control_value(key: str, value: int) -> str
```
Format giá trị hiển thị: `auto_camera` → `"AUTO"/"MANUAL"`, `roi_width` → `"70%"`, v.v.

```python
def _adjust_camera_control_value(state: dict, selected_idx: int, direction: int) -> None
```
Tăng/giảm 1 bước thông số được chọn, giới hạn bởi `[min, max]`.

### 3. Mở/đóng camera

```python
def _open_camera(camera_index) -> cv2.VideoCapture
```
Mở camera với backend tối ưu: `CAP_DSHOW` (Windows) hoặc `CAP_V4L2` (Linux). Fallback về backend tự động nếu thất bại.

```python
def _open_selected_camera(camera_index) -> cv2.VideoCapture
```
Thử mở camera tối đa 5 lần (retry 0.25s). Hỗ trợ index int/str và device path `/dev/videoN`. Ném `RuntimeError` nếu vẫn thất bại.

```python
def _hard_release_camera(cap, window_names: tuple = ()) -> None
```
Release camera, đóng window, flush `cv2.waitKey(1)` x3, sleep 0.2s để tránh stale state.

```python
def _set_camera_auto_mode(cap, enabled: bool) -> None
```
Bật/tắt autofocus và auto-exposure. Thử nhiều cách vì API khác nhau giữa backend.

### 4. Tiền xử lý ảnh QR

```python
def _preprocess_for_qr(frame: np.ndarray) -> list[np.ndarray]
```

Pipeline tối ưu tốc độ:
1. **Downscale 50%** — pyzbar decode ảnh nhỏ nhanh ~4×
2. **Grayscale** — giảm memory bandwidth
3. **OTSU threshold** — nhanh, tốt khi ánh sáng đồng đều *(thử trước)*
4. **Adaptive threshold** — chậm hơn, tốt hơn với ánh sáng không đều *(fallback)*

Trả về `[otsu, adaptive, gray]` — decode theo thứ tự.

```python
def _decode_qr(images: list[np.ndarray]) -> str | None
```
Thử decode từng ảnh qua `pyzbar.decode(..., symbols=[QRCODE])`. Dừng ngay khi thành công.

```python
def _is_likely_qr_payload(payload: str) -> bool
```
Kiểm tra nhanh payload có phải base64 AES-GCM không: strip prefix `v1:`, kiểm tra độ dài ≥16 và chia hết 4, kiểm tra charset base64.

### 5. Giải mã AES-GCM

```python
def _load_keys() -> list[bytes]
```
Load từ `AES_GCM_KEY_B64` (primary) và `AES_GCM_ALT_KEYS_B64` (danh sách phụ, phân cách bởi `,`). Decode base64 → bytes.

```python
def _decode_payload(payload: str) -> bytes
```
Strip prefix `v1:` và base64-decode payload thô.

```python
def decrypt_patient_id(payload: str, keys: list[bytes]) -> str
```
Giải mã AES-256-GCM:
- Tách `nonce = raw[:12]`, `ciphertext+tag = raw[12:]`
- Thử từng key cho đến khi thành công
- Ném `ValueError` nếu tất cả key đều thất bại

### 6. Nghiệp vụ Firebase

```python
def _process_payload_and_update(
    payload: str,
    patients_path: str = "patients",
    appointments_path: str = "appointments",
) -> tuple[str, str]
```

**Flow xử lý:**

```
payload (base64)
    │
    ▼
decrypt_patient_id() → appointment_id
    │
    ▼
get_appointment(appointment_id)
    │
    ├─ Không tìm thấy → trả về lỗi
    ├─ status = "arrived" → trả về _ALREADY_ARRIVED_SENTINEL (silent skip)
    ├─ status = "cancelled/expired" → trả về thông báo hủy
    │
    ▼
get_patient(patientID từ appointment)
    │
    ▼
update_global_appointment_status(appointment_id, "arrived")
    │
    ▼
add_patient_to_queue(doctorID, appointment_id, patient_name)
    │
    ▼
return ("", patient_name)  ← thành công
```

**Trả về:** `(message: str, patient_name: str)`
- `message = ""` → thành công
- `message = _ALREADY_ARRIVED_SENTINEL` → đã check-in rồi, bỏ qua
- Các trường hợp khác → thông báo lỗi

**Status "arrived" được nhận:**
```python
{"đã đến", "da den", "arrived", "checked_in", "checked in"}
```

**Status "cancelled" được nhận:**
```python
{"cancelled", "canceled", "da huy", "đã hủy", "qua han", "quá hạn", "expired"}
```

```python
def _extract_patient_name(data: Any) -> str
```
Thử các field phổ biến theo thứ tự: `name`, `full_name`, `fullName`, `patient_name`, `patientName`, `ho_ten`, `hoTen`, `ten`, `displayName`.

### 7. Vẽ UI lên frame (OpenCV + Pillow)

```python
def _draw_scan_frame(frame: np.ndarray, roi: tuple) -> np.ndarray
```
Vẽ 4 góc khung quét xanh lá (không tạo nền trắng — tiết kiệm ~5ms/frame).

```python
def _draw_text_pil(img, text, xy, size=36, color) -> np.ndarray
def _draw_text_centered_pil(img, text, y, size=28, color) -> np.ndarray
```
Vẽ text Unicode/tiếng Việt bằng Pillow. Sử dụng font DejaVuSans (Linux) hoặc Arial (Windows).

```python
def _resize_fill(frame, target_w, target_h) -> np.ndarray
```
Resize frame để fill toàn màn hình (không letterbox). Dùng `INTER_LINEAR` (phóng to) hoặc `INTER_AREA` (thu nhỏ).

```python
def _draw_hud_panel(img, W, H, last_message="") -> np.ndarray
```
Vẽ HUD panel phía dưới frame với trạng thái và phím tắt. Nền mờ đen (alpha blend).

```python
def _draw_step_ui(img, step: int, W, H) -> None
```
Hiển thị 3 bước hướng dẫn (1: Đưa QR vào khung, 2: Giữ ổn định, 3: Đang xử lý) với màu khác nhau theo bước hiện tại.

```python
def _draw_config_text_view(frame, state, selected_idx, theme) -> np.ndarray
```
Render toàn bộ UI cấu hình camera: camera preview bên trái + sidebar thông số bên phải. Highlight thông số được chọn. Vẽ thanh slider + knob cho từng thông số.

---

## Hàm công khai chính

### `_configure_camera_preview(camera_index, theme) -> dict`

Mở UI cấu hình camera tương tác (cửa sổ OpenCV). Blocking cho đến khi người dùng nhấn ESC.

**Phím tắt:**

| Phím | Chức năng |
|------|-----------|
| `↑` / `W` | Chọn thông số phía trên |
| `↓` / `S` | Chọn thông số phía dưới |
| `←` / `A` / `J` / `-` | Giảm giá trị |
| `→` / `L` / `+` / `=` | Tăng giá trị |
| `M` | Toggle Auto/Manual Camera |
| `P` | Áp dụng QR Preset tối ưu |
| `R` | Reset về giá trị đã load |
| `D` | Reset về factory default |
| `ESC` | Lưu và thoát |

**QR Preset (phím P):**
```python
{brightness: 68, contrast: 1.30, exposure: -3, gain: 6,
 focus: 42, sharpness: 74, saturation: 60, roi: 70%×70%}
```

### `scan_from_camera(camera_index, patients_path, appointments_path, config) -> str | None`

Vòng lặp quét QR chính. Blocking cho đến khi nhấn `Q` hoặc `ESC`.

**Tối ưu hiệu năng (cho Raspberry Pi 4):**

| Kỹ thuật | Lợi ích |
|----------|---------|
| Downscale 50% trước decode | Pyzbar nhanh ~4× |
| `decode_interval = 3` | Chỉ decode mỗi 3 frame | 
| `MJPEG fourcc` | Giảm USB bandwidth |
| `CAP_PROP_BUFFERSIZE = 1` | Luôn lấy frame mới nhất |
| Precompute ROI một lần | Không tính lại mỗi frame |
| Cache font | Load font một lần duy nhất |
| Vẽ scan_frame trực tiếp | Không tạo `np.ones_like` |

**Màn hình kết quả:**

| Loại | Màu nền | Icon |
|------|---------|------|
| Thành công | Trắng | ✓ xanh lá |
| Lịch hẹn hủy/quá hạn | Trắng | ✗ đỏ |
| Lỗi kỹ thuật | Trắng | ! vàng |

Sau khi quét thành công, màn hình kết quả hiển thị 60 frame (~2 giây), sau đó tự reset để quét tiếp.

**Phím thoát:** `Q` hoặc `ESC`

---

## Luồng dữ liệu scan_from_camera

```
Camera frame
    │
    ├─ [mỗi 3 frame] ──► ROI crop ──► _preprocess_for_qr()
    │                                          │
    │                                    [otsu, adaptive, gray]
    │                                          │
    │                                    _decode_qr()
    │                                          │
    │                                    _is_likely_qr_payload()
    │                                          │
    │                              _process_payload_and_update()
    │                                          │
    │                               ┌──────────┴──────────┐
    │                          thành công              lỗi/hủy
    │                               │                      │
    │                         update Firebase         hiển thị lỗi
    │                         add_to_queue
    │
    └─ [mỗi frame] ──► _draw_scan_frame() ──► cv2.imshow()
```

---

## Biến môi trường

| Tên | Bắt buộc | Mô tả |
|-----|----------|-------|
| `AES_GCM_KEY_B64` | ✓ | Khóa AES-256-GCM chính, base64 |
| `AES_GCM_ALT_KEYS_B64` | ✗ | Danh sách khóa phụ, phân cách bởi `,` |

---

## Thread Safety

```python
camera_lock = threading.Lock()
```

Dùng để serialize các thao tác mở camera (`_open_selected_camera` và `_configure_camera_preview`). Tránh xung đột khi cả GUI thread lẫn scan thread cùng cố mở device.
