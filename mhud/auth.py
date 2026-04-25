from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

import streamlit as st


@dataclass(frozen=True)
class User:
    username: str
    role: str  # "Admin" | "Data Entry"


def _load_users_from_secrets() -> dict[str, dict[str, str]]:
    # Optional:
    # [auth]
    # users = [
    #   {username="x", password="y", role="Admin"},
    #   {username="u", password="p", role="Data Entry"},
    # ]
    auth = st.secrets.get("auth", None)
    if not auth:
        return {}
    users: list[dict[str, Any]] = auth.get("users", [])  # type: ignore[assignment]
    out: dict[str, dict[str, str]] = {}
    for u in users or []:
        try:
            username = str(u.get("username", "")).strip()
            password = str(u.get("password", ""))
            role = str(u.get("role", "Data Entry")).strip() or "Data Entry"
        except Exception:
            continue
        if username:
            out[username] = {"password": password, "role": role}
    return out


def get_users() -> dict[str, dict[str, str]]:
    users = {
        "admin": {"password": "admin123", "role": "Admin"},
    }
    users.update(_load_users_from_secrets())
    return users


def verify_login(username: str, password: str) -> User | None:
    username = (username or "").strip()
    password = password or ""
    users = get_users()
    if username not in users:
        return None
    # constant-time compare for password string
    if not hmac.compare_digest(password, users[username]["password"]):
        return None
    role = users[username].get("role", "Data Entry") or "Data Entry"
    if role not in ("Admin", "Data Entry"):
        role = "Data Entry"
    return User(username=username, role=role)


def logout() -> None:
    st.session_state.pop("user", None)
    st.session_state.pop("nav", None)

