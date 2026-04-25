from __future__ import annotations

import re
from dataclasses import dataclass


NATIONAL_ID_RE = re.compile(r"^\d{14}$")
PHONE_RE = re.compile(r"^01\d{9}$")


@dataclass(frozen=True)
class ValidationError:
    field: str
    message: str


def validate_national_id(value: str) -> str | None:
    v = (value or "").strip()
    if not NATIONAL_ID_RE.match(v):
        return "الرقم القومي يجب أن يكون 14 رقمًا بالضبط."
    return None


def validate_phone(value: str) -> str | None:
    v = (value or "").strip()
    if not PHONE_RE.match(v):
        return "رقم الهاتف يجب أن يكون 11 رقمًا ويبدأ بـ 01."
    return None


def require_nonempty(label: str, value: str | None) -> str | None:
    v = (value or "").strip()
    if not v:
        return f"حقل ({label}) مطلوب."
    return None

