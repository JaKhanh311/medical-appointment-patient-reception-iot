"""
Priority Category Definitions for Appointments

Defines 4-tier priority system with corresponding metadata,
applicable beneficiary groups, and example keywords.
"""

from enum import Enum
from typing import Dict, List


class PriorityTier(Enum):
    """Priority tier levels (lowest to highest)"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


PRIORITY_CATEGORIES = {
    "low": {
        "tier": "low",
        "code": "P1_LOW",
        "label": "Bình thường",
        "label_full": "Priority 1 - Bình thường (FCFS)",
        "boost": 0,
        "type": "normal",
        "description": "Bệnh nhân bình thường, không có ưu tiên đặc biệt",
        "icon": "✓",
        "color": "gray",
        "beneficiaries": [],
        "keywords": [
            "bình thường",
            "binh thuong",
            "thông thường",
            "thong thuong",
        ],
    },
    "medium": {
        "tier": "medium",
        "code": "P2_MEDIUM",
        "label": "Ưu tiên xã hội",
        "label_full": "Priority 2 - Ưu tiên xã hội",
        "boost": 80,
        "type": "social",
        "description": "Bệnh nhân thuộc nhóm đối tượng xã hội cần ưu tiên",
        "icon": "◎",
        "color": "blue",
        "beneficiaries": [
            "Trẻ em dưới 6 tuổi",
            "Phụ nữ mang thai",
            "Người cao tuổi (≥80 tuổi)",
            "Người khuyết tật",
            "Thương binh, liệt sĩ",
            "Người có công với nước",
        ],
        "keywords": [
            # Children
            "trẻ em",
            "tre em",
            "dưới 6 tuổi",
            "duoi 6 tuoi",
            "em bé",
            "em be",
            "bé nhỏ",
            "be nho",
            # Pregnant women
            "mang thai",
            "có thai",
            "co thai",
            "thành phụ",
            "thanh phu",
            "phụ nữ mang thai",
            "phu nu mang thai",
            # Elderly
            "cao tuổi",
            "cao tuoi",
            "trên 80",
            "tren 80",
            "80 tuổi",
            "80 tuoi",
            "cao niên",
            "cao nien",
            "già",
            "gia",
            "ông bà",
            "ong ba",
            # Disability
            "khuyết tật",
            "khuyet tat",
            "tàn tật",
            "tan tat",
            "tật nhân",
            "tat nhan",
            "không may",
            "khong may",
            "người khuyết tật",
            "nguoi khuyet tat",
            # Veterans & service
            "có công",
            "co cong",
            "thương binh",
            "thuong binh",
            "liệt sĩ",
            "liet si",
            "quân nhân",
            "quan nhan",
        ],
    },
    "high": {
        "tier": "high",
        "code": "P3_HIGH",
        "label": "Ưu tiên y khoa",
        "label_full": "Priority 3 - Ưu tiên y khoa",
        "boost": 140,
        "type": "medical",
        "description": "Bệnh nhân có tình trạng sức khỏe cần ưu tiên khám ngay",
        "icon": "◈",
        "color": "orange",
        "beneficiaries": [
            "Đau nhiều, khó chịu",
            "Khó thở (mức độ nhẹ-vừa)",
            "Sốt cao (≥39°C)",
            "Sau phẫu thuật gần đây",
            "Suy kiệt, yếu đuối",
            "Có dấu hiệu nguy hiểm",
        ],
        "keywords": [
            # Pain & discomfort
            "đau nhiều",
            "dau nhieu",
            "khó thở nhẹ",
            "kho tho nhe",
            "khó thở vừa",
            "kho tho vua",
            "khó chịu",
            "kho chiu",
            # Fever
            "sốt cao",
            "sot cao",
            "sốt",
            "sot",
            "39 độ",
            "39 do",
            "40 độ",
            "40 do",
            # Post-op
            "sau phẫu thuật",
            "sau phau thuat",
            "hậu phẫu thuật",
            "hau phau thuat",
            "sau ca mổ",
            "sau ca mo",
            "vết mổ",
            "vet mo",
            # Weakness & complications
            "suy kiệt",
            "suy kiet",
            "suy nhược",
            "suy nhuoc",
            "yếu",
            "yeu",
            "yếu đuối",
            "yeu duoi",
            # Critical signs
            "nguy cơ chuyển nặng",
            "nguy co chuyen nang",
            "dấu hiệu nguy hiểm",
            "dau hieu nguy hiem",
            "tim đập nhanh",
            "tim dap nhanh",
            "huyết áp cao",
            "huyet ap cao",
            "huyết áp thấp",
            "huyet ap thap",
        ],
    },
    "critical": {
        "tier": "critical",
        "code": "P4_CRITICAL",
        "label": "Cấp cứu",
        "label_full": "Priority 4 - Cấp cứu (Khẩn cấp)",
        "boost": 220,
        "type": "critical",
        "description": "Trường hợp khẩn cấp, đe dọa tính mạng - cần hỗ trợ ngay lập tức",
        "icon": "◆",
        "color": "red",
        "beneficiaries": [
            "Mất ý thức",
            "Chấn thương nặng",
            "Đột quỵ",
            "Nhồi máu cơ tim",
            "Shock",
            "Khó thở nặng",
        ],
        "keywords": [
            # Loss of consciousness
            "mất ý thức",
            "mat y thuc",
            "mất nước",
            "mat nuoc",
            "bất tỉnh",
            "bat tinh",
            "ngất",
            "ngat",
            # Severe trauma
            "chấn thương",
            "chan thuong",
            "chấn thương nặng",
            "chan thuong nang",
            "gãy xương",
            "gay xuong",
            "vỡ",
            "vo",
            # Stroke
            "đột quỵ",
            "dot quy",
            "liệt nửa người",
            "liet nua nguoi",
            "nói không rõ",
            "noi khong ro",
            # MI
            "nhồi máu",
            "nhoi mau",
            "nhồi máu cơ tim",
            "nhoi mau co tim",
            "đau ngực",
            "dau nguc",
            # Shock
            "shock",
            "sốc",
            "soc",
            "huyết áp sụt",
            "huyet ap sut",
            # Severe dyspnea
            "khó thở nặng",
            "kho tho nang",
            "không thể thở",
            "khong the tho",
            "thở không đủ",
            "tho khong du",
            # Emergency marker
            "cấp cứu",
            "cap cuu",
            "khẩn cấp",
            "khan cap",
            "tình trạng nghiêm trọng",
            "tinh trang nghiem trong",
        ],
    },
}


def get_priority_category(tier: str) -> Dict:
    """Get priority category definition by tier name"""
    tier_lower = (tier or "").strip().lower()
    return PRIORITY_CATEGORIES.get(tier_lower)


def get_all_categories() -> Dict:
    """Get all priority categories (for UI dropdown/display)"""
    return PRIORITY_CATEGORIES


def get_category_for_display(tier: str) -> Dict:
    """Get category info formatted for UI display"""
    category = get_priority_category(tier)
    if not category:
        return get_priority_category("low")
    return category


def extract_tier_from_keywords(text: str) -> str:
    """
    Analyze text and return most likely tier (critical > high > medium > low).
    Used when no explicit tier is provided.
    """
    from services.RTDB_utils import _normalize_text_no_accents

    normalized = _normalize_text_no_accents(text)

    # Check in descending priority order
    tiers = ["critical", "high", "medium", "low"]
    for tier in tiers:
        category = PRIORITY_CATEGORIES.get(tier)
        if category:
            keywords = category.get("keywords", [])
            if any(kw in normalized for kw in keywords):
                return tier

    return "low"  # Default


# Helper for forms/UI
PRIORITY_CHOICES = [
    ("low", "Priority 1 - Bình thường (FCFS)"),
    ("medium", "Priority 2 - Ưu tiên xã hội"),
    ("high", "Priority 3 - Ưu tiên y khoa"),
    ("critical", "Priority 4 - Cấp cứu"),
]

PRIORITY_COLORS = {
    "low": "#6c757d",  # gray
    "medium": "#0d6efd",  # blue
    "high": "#fd7e14",  # orange
    "critical": "#dc3545",  # red
}

PRIORITY_ICONS = {
    "low": "✓",
    "medium": "◎",
    "high": "◈",
    "critical": "◆",
}
