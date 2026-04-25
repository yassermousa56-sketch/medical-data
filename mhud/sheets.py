from __future__ import annotations

import datetime as dt
from typing import Any

import streamlit as st


CORE_WORKSHEET = "core_visits"
META_WORKSHEET = "_meta_tabs"


def _require_secrets() -> tuple[dict[str, Any], str]:
    if "gcp_service_account" not in st.secrets or "sheets" not in st.secrets:
        raise RuntimeError("Missing required secrets: [gcp_service_account] and [sheets].")
    sa = dict(st.secrets["gcp_service_account"])
    spreadsheet_id = str(st.secrets["sheets"].get("spreadsheet_id", "")).strip()
    if not spreadsheet_id or spreadsheet_id == "YOUR_SPREADSHEET_ID":
        raise RuntimeError("Please set [sheets].spreadsheet_id in .streamlit/secrets.toml")
    if sa.get("project_id") in (None, "", "YOUR_PROJECT_ID"):
        raise RuntimeError("Please fill [gcp_service_account] in .streamlit/secrets.toml")
    return sa, spreadsheet_id


@st.cache_resource(show_spinner=False)
def get_gspread_client() -> Any:
    sa, _ = _require_secrets()
    try:
        import gspread  # imported lazily to avoid hard import failures on some Windows policies
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google Sheets client failed to import. "
            "Your Windows policy may be blocking native crypto DLLs required by google-auth/cryptography. "
            f"Original error: {e}"
        )
    return gspread.service_account_from_dict(sa)


@st.cache_resource(show_spinner=False)
def get_spreadsheet() -> Any:
    client = get_gspread_client()
    _, spreadsheet_id = _require_secrets()
    return client.open_by_key(spreadsheet_id)


def get_or_create_worksheet(title: str, headers: list[str]) -> Any:
    ss = get_spreadsheet()
    try:
        import gspread
    except Exception:
        gspread = None  # type: ignore[assignment]
    try:
        ws = ss.worksheet(title)
    except Exception as e:
        if gspread is not None and isinstance(e, gspread.WorksheetNotFound):
            ws = ss.add_worksheet(title=title, rows=2000, cols=max(10, len(headers) + 2))
            ws.append_row(headers, value_input_option="USER_ENTERED")
            return ws
        # Some environments wrap exceptions differently; try creating by default.
        ws = ss.add_worksheet(title=title, rows=2000, cols=max(10, len(headers) + 2))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        return ws

    # Ensure header exists (best-effort, not destructive)
    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []
    if not first_row and headers:
        ws.append_row(headers, value_input_option="USER_ENTERED")
    return ws


def safe_sheet_title(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return "untitled"
    # Google Sheets worksheet title constraints: <= 100 chars, no : \ / ? * [ ]
    banned = set(":\\/?*[]")
    cleaned = "".join("_" if ch in banned else ch for ch in n)
    cleaned = " ".join(cleaned.split())
    return cleaned[:100]


def append_row_to_worksheet(worksheet_title: str, headers: list[str], row: list[Any]) -> None:
    ws = get_or_create_worksheet(worksheet_title, headers=headers)
    ws.append_row([_stringify(v) for v in row], value_input_option="USER_ENTERED")


def _stringify(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


@st.cache_data(show_spinner=False, ttl=15)
def read_all_records(worksheet_title: str) -> list[dict[str, Any]]:
    ss = get_spreadsheet()
    ws = ss.worksheet(worksheet_title)
    return ws.get_all_records()

