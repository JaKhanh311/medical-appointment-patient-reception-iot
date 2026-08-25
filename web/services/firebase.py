import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials, db as firebasedb
import json
import os
from urllib import request as urllib_request
from urllib import error as urllib_error

try:
    from django.conf import settings
except Exception:
    settings = None

cred = credentials.Certificate("firebase-key.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://nckh-f46fb-default-rtdb.firebaseio.com'
    })

db = firebasedb.reference()


def _get_firebase_web_api_key():
    """Resolve Firebase Web API key from env vars first, then Django settings."""
    env_candidates = (
        os.getenv("FIREBASE_WEB_API_KEY", ""),
        os.getenv("FIREBASE_API_KEY", ""),
        os.getenv("GOOGLE_API_KEY", ""),
    )
    for value in env_candidates:
        value = (value or "").strip()
        if value:
            return value

    if settings is not None:
        setting_candidates = (
            getattr(settings, "FIREBASE_WEB_API_KEY", ""),
            getattr(settings, "FIREBASE_API_KEY", ""),
            getattr(settings, "GOOGLE_API_KEY", ""),
        )
        for value in setting_candidates:
            value = str(value or "").strip()
            if value:
                return value

    return ""


def _friendly_firebase_auth_error(code, default_prefix):
    error_map = {
        "EMAIL_NOT_FOUND": "Email không tồn tại trên Firebase Authentication.",
        "INVALID_PASSWORD": "Mật khẩu không đúng.",
        "INVALID_LOGIN_CREDENTIALS": "Thông tin đăng nhập không hợp lệ.",
        "USER_DISABLED": "Tài khoản đã bị vô hiệu hóa.",
        "PASSWORD_LOGIN_DISABLED": (
            "Firebase Authentication đang tắt Email/Password sign-in. "
            "Hãy bật provider Email/Password trong Firebase Console > Authentication > Sign-in method."
        ),
        "OPERATION_NOT_ALLOWED": (
            "Firebase Authentication chưa bật phương thức Email/Password. "
            "Hãy bật provider Email/Password trong Firebase Console > Authentication > Sign-in method."
        ),
    }
    return error_map.get(code, f"{default_prefix}: {code or 'UNKNOWN_ERROR'}")


def firebase_sign_in_with_email_password(email, password):
    """Authenticate user against Firebase Authentication using email/password."""
    api_key = _get_firebase_web_api_key()
    if not api_key:
        raise ValueError(
            "Thiếu Firebase Web API key. Vui lòng cấu hình FIREBASE_WEB_API_KEY "
            "(hoặc FIREBASE_API_KEY/GOOGLE_API_KEY) trong biến môi trường."
        )

    endpoint = (
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        f"?key={api_key}"
    )
    payload = {
        "email": (email or "").strip(),
        "password": password or "",
        "returnSecureToken": True,
    }
    body = json.dumps(payload).encode("utf-8")

    req = urllib_request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        try:
            err_data = json.loads(exc.read().decode("utf-8"))
            code = (
                err_data.get("error", {})
                .get("message", "")
                .strip()
            )
        except Exception:
            code = ""

        friendly_message = _friendly_firebase_auth_error(code, "Đăng nhập Firebase thất bại")
        raise ValueError(friendly_message) from exc


def firebase_create_user_with_email_password(email, password, display_name=""):
    """Create user in Firebase Authentication using Identity Toolkit REST API."""
    api_key = _get_firebase_web_api_key()
    if not api_key:
        raise ValueError(
            "Thiếu Firebase Web API key. Vui lòng cấu hình FIREBASE_WEB_API_KEY "
            "(hoặc FIREBASE_API_KEY/GOOGLE_API_KEY) trong biến môi trường."
        )

    endpoint = (
        "https://identitytoolkit.googleapis.com/v1/accounts:signUp"
        f"?key={api_key}"
    )
    payload = {
        "email": (email or "").strip(),
        "password": password or "",
        "returnSecureToken": True,
    }

    display_name = (display_name or "").strip()
    if display_name:
        payload["displayName"] = display_name

    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        try:
            err_data = json.loads(exc.read().decode("utf-8"))
            code = (
                err_data.get("error", {})
                .get("message", "")
                .strip()
            )
        except Exception:
            code = ""

        error_map = {
            "EMAIL_EXISTS": "Email đã tồn tại trên Firebase Authentication.",
            "INVALID_EMAIL": "Email không hợp lệ.",
            "WEAK_PASSWORD : Password should be at least 6 characters": "Mật khẩu phải có ít nhất 6 ký tự.",
            "WEAK_PASSWORD": "Mật khẩu quá yếu, vui lòng dùng tối thiểu 6 ký tự.",
            "PASSWORD_LOGIN_DISABLED": (
                "Firebase Authentication đang tắt Email/Password sign-in. "
                "Hãy bật provider Email/Password trong Firebase Console > Authentication > Sign-in method."
            ),
            "OPERATION_NOT_ALLOWED": (
                "Firebase Authentication chưa bật phương thức Email/Password. "
                "Hãy bật provider Email/Password trong Firebase Console > Authentication > Sign-in method."
            ),
        }
        friendly_message = error_map.get(code, f"Tạo tài khoản Firebase thất bại: {code or 'UNKNOWN_ERROR'}")
        raise ValueError(friendly_message) from exc


def firebase_update_user_account(uid, email=None, password=None, display_name=None):
    """Update an existing Firebase Authentication user with admin credentials."""
    uid = (uid or "").strip()
    if not uid:
        raise ValueError("Thiếu UID Firebase để cập nhật tài khoản.")

    update_kwargs = {}

    if email is not None:
        email = (email or "").strip()
        if not email:
            raise ValueError("Email Firebase Authentication không được để trống.")
        update_kwargs["email"] = email

    if password is not None:
        password = password or ""
        if len(password) < 6:
            raise ValueError("Mật khẩu phải có ít nhất 6 ký tự.")
        update_kwargs["password"] = password

    if display_name is not None:
        update_kwargs["display_name"] = (display_name or "").strip()

    if not update_kwargs:
        return None

    try:
        return firebase_auth.update_user(uid, **update_kwargs)
    except Exception as exc:
        message = str(exc).strip() or "UNKNOWN_ERROR"
        raise ValueError(f"Cập nhật tài khoản Firebase thất bại: {message}") from exc


def firebase_get_user_by_email(email):
    """Get Firebase Authentication user by email using admin credentials."""
    email = (email or "").strip()
    if not email:
        raise ValueError("Email không được để trống.")

    try:
        return firebase_auth.get_user_by_email(email)
    except firebase_auth.UserNotFoundError as exc:
        raise ValueError("Không tìm thấy tài khoản Firebase theo email.") from exc
    except Exception as exc:
        message = str(exc).strip() or "UNKNOWN_ERROR"
        raise ValueError(f"Không thể truy vấn tài khoản Firebase theo email: {message}") from exc


def firebase_get_user_by_uid(uid):
    """Get Firebase Authentication user by UID using admin credentials."""
    uid = (uid or "").strip()
    if not uid:
        raise ValueError("UID không được để trống.")

    try:
        return firebase_auth.get_user(uid)
    except firebase_auth.UserNotFoundError as exc:
        raise ValueError("Không tìm thấy tài khoản Firebase theo UID.") from exc
    except Exception as exc:
        message = str(exc).strip() or "UNKNOWN_ERROR"
        raise ValueError(f"Không thể truy vấn tài khoản Firebase theo UID: {message}") from exc


def firebase_user_exists(uid=None, email=None):
    """Check if a Firebase Authentication account exists by UID or email."""
    uid = (uid or "").strip()
    email = (email or "").strip()

    if uid:
        try:
            firebase_get_user_by_uid(uid)
            return True
        except ValueError as exc:
            if str(exc) == "Không tìm thấy tài khoản Firebase theo UID.":
                return False
            raise

    if email:
        try:
            firebase_get_user_by_email(email)
            return True
        except ValueError as exc:
            if str(exc) == "Không tìm thấy tài khoản Firebase theo email.":
                return False
            raise

    raise ValueError("Cần cung cấp UID hoặc email để kiểm tra tài khoản Firebase.")


