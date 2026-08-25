"""
Authentication and settings services — ported from qr_scan_gui.py.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

# IoT project root (3 parents up: auth_service.py → services/ → pyside6_app/ → IoT/)
IOT_DIR = Path(__file__).resolve().parent.parent.parent

ENV_PATH = IOT_DIR / ".env"
SETTINGS_PATH = IOT_DIR / "gui_settings.json"

FIREBASE_CLIENT_CONFIG_CANDIDATES = [
    IOT_DIR / "google-services (1).json",
    IOT_DIR / "google-services.json",
]

DEFAULT_SETTINGS: dict = {
    "scanner": {
        "camera_index": "",
        "patients_path": "patients",
        "appointments_path": "appointment_new",
    },
    "appearance": {
        "theme": "dark",
    },
    "auth": {
        "remember_login": False,
        "email": "",
        "password": "",
    },
}


# ── Firebase client config ────────────────────────────────────────────────────

def _find_firebase_client_config() -> Path | None:
    for candidate in FIREBASE_CLIENT_CONFIG_CANDIDATES:
        if candidate.exists():
            return candidate
    matches = sorted(IOT_DIR.glob("google-services*.json"))
    return matches[0] if matches else None


def get_firebase_api_key() -> str:
    path = _find_firebase_client_config()
    if not path:
        raise FileNotFoundError("Không tìm thấy tệp google-services.json.")
    config = json.loads(path.read_text(encoding="utf-8"))
    clients = config.get("client")
    if not isinstance(clients, list) or not clients:
        raise RuntimeError("Tệp Firebase client config không hợp lệ.")
    client = clients[0]
    api_key_entries = client.get("api_key")
    if not isinstance(api_key_entries, list) or not api_key_entries:
        raise RuntimeError("Không tìm thấy API key.")
    entry = api_key_entries[0]
    api_key = entry.get("current_key") if isinstance(entry, dict) else ""
    if not api_key:
        raise RuntimeError("API key trống.")
    return str(api_key)


# ── Firebase Authentication ───────────────────────────────────────────────────

def firebase_sign_in(email: str, password: str) -> dict:
    """Sign in with email/password via Firebase Identity Toolkit REST API.
    Only admin accounts are allowed to log in to the IoT device.
    """
    api_key = get_firebase_api_key()
    url = (
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        f"?key={api_key}"
    )
    payload = json.dumps(
        {"email": email, "password": password, "returnSecureToken": True}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            msg = body.get("error", {}).get("message", str(exc))
        except Exception:
            msg = str(exc)
        # Translate common Firebase error codes
        friendly = {
            "EMAIL_NOT_FOUND": "Email không tồn tại trong hệ thống.",
            "INVALID_PASSWORD": "Mật khẩu không đúng.",
            "INVALID_EMAIL": "Định dạng email không hợp lệ.",
            "USER_DISABLED": "Tài khoản bị vô hiệu hóa.",
            "TOO_MANY_ATTEMPTS_TRY_LATER": "Quá nhiều lần thử, hãy thử lại sau.",
            "INVALID_LOGIN_CREDENTIALS": "Email hoặc mật khẩu không đúng.",
        }
        raise RuntimeError(friendly.get(str(msg), str(msg))) from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    # --- Admin-only check ---
    # Verify the user has admin role by checking Firebase RTDB
    uid = result.get("localId", "")
    id_token = result.get("idToken", "")
    is_admin, reason = _is_admin_user(uid, id_token)
    if not is_admin:
        raise RuntimeError(f"Tài khoản không có quyền quản trị. {reason}")

    return result


def _is_admin_user(uid: str, id_token: str) -> tuple[bool, str]:
    """Check if user has role=admin in Firebase RTDB node users/{uid}.
    Logic giống authenticate_admin_firebase trên web:
    1. Đọc users/{uid}/role
    2. Nếu không có, scan toàn bộ users tìm theo email
    Returns: (is_admin, reason_if_failed)
    """
    if not uid or not id_token:
        return False, "Thiếu UID hoặc token."
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
        project_id = os.environ.get("FIREBASE_PROJECT_ID", "")
        if not project_id:
            for sa_file in IOT_DIR.glob("*firebase-adminsdk*.json"):
                sa_data = json.loads(sa_file.read_text(encoding="utf-8"))
                project_id = sa_data.get("project_id", "")
                if project_id:
                    break
        if not project_id:
            return True, ""  # Không xác minh được → cho qua

        base_url = f"https://{project_id}-default-rtdb.firebaseio.com"

        # Bước 1: Đọc trực tiếp users/{uid}
        url1 = f"{base_url}/users/{uid}.json?auth={id_token}"
        req1 = urllib.request.Request(url1, method="GET")
        with urllib.request.urlopen(req1, timeout=10) as resp1:
            user_data = json.loads(resp1.read().decode("utf-8"))
            if isinstance(user_data, dict) and user_data:
                role = str(user_data.get("role", "")).strip().lower()
                if role == "admin":
                    return True, ""
                else:
                    return False, f"users/{uid} có role='{role}', không phải admin."

        # Bước 2: Fallback — scan toàn bộ users tìm theo email
        api_key = get_firebase_api_key()
        lookup_url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={api_key}"
        lookup_payload = json.dumps({"idToken": id_token}).encode("utf-8")
        lookup_req = urllib.request.Request(
            lookup_url, data=lookup_payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        current_email = ""
        with urllib.request.urlopen(lookup_req, timeout=10) as resp_lookup:
            lookup_data = json.loads(resp_lookup.read().decode("utf-8"))
            users_list = lookup_data.get("users", [])
            if users_list:
                current_email = users_list[0].get("email", "").strip().lower()

        if not current_email:
            return False, "Không lấy được email từ Firebase Auth."

        # Scan users node tìm theo email (giống logic web)
        url2 = f"{base_url}/users.json?auth={id_token}"
        req2 = urllib.request.Request(url2, method="GET")
        with urllib.request.urlopen(req2, timeout=15) as resp2:
            all_users = json.loads(resp2.read().decode("utf-8"))
            if isinstance(all_users, dict):
                for key, value in all_users.items():
                    if not isinstance(value, dict):
                        continue
                    user_email = str(value.get("email", "")).strip().lower()
                    if user_email == current_email:
                        role = str(value.get("role", "")).strip().lower()
                        if role == "admin":
                            return True, ""
                        else:
                            return False, f"Tìm thấy user theo email nhưng role='{role}'."

        return False, f"Không tìm thấy user với email '{current_email}' trong node users trên RTDB."
    except Exception as exc:
        return False, f"Lỗi kiểm tra: {exc}"


# ── Settings ─────────────────────────────────────────────────────────────────

def load_settings() -> dict:
    s: dict = json.loads(json.dumps(DEFAULT_SETTINGS))
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            for section in ("scanner", "appearance", "auth"):
                if isinstance(loaded.get(section), dict):
                    s[section].update(loaded[section])
        except Exception:
            pass
    save_settings(s)
    return s


def save_settings(s: dict) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── .env management ───────────────────────────────────────────────────────────

def read_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def write_env_file(updates: dict[str, str]) -> None:
    existing = (
        ENV_PATH.read_text(encoding="utf-8").splitlines()
        if ENV_PATH.exists()
        else []
    )
    replaced: set[str] = set()
    out: list[str] = []
    for line in existing:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        k = line.split("=", 1)[0].strip()
        if k in updates:
            out.append(f"{k}={updates[k]}")
            replaced.add(k)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in replaced:
            out.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(out).strip() + "\n", encoding="utf-8")
