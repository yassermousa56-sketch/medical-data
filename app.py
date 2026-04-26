from __future__ import annotations

"""
Production-ready Streamlit Medical Data Management System.

Key features:
- Modern Medical UI (white/blue) + centered Login Card.
- Secure authentication: credentials ONLY from st.secrets.
- RBAC: Admin vs User.
- Admin-only: Dashboard, Tab Builder, Manage (Edit/Delete) dynamic tabs, Export (Excel/PDF).
- User-only: Data entry forms (core + dynamic) with restricted UI.
- Strict validation (National ID / Phone).
- Audit trail: username + role + timestamp stored on every submission.
- Google Sheets backend (append-only rows; soft-delete for tab definitions).
"""

import datetime as dt
import hmac
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Iterable, Literal

import plotly.graph_objects as go
import streamlit as st

# ==========================
# CONFIG + CONSTANTS
# ==========================

APP_TITLE = "نظام إدارة البيانات الطبية"

CORE_WORKSHEET = "core_visits"
META_WORKSHEET = "_meta_tabs"  # append-only tab definitions (last-write-wins)

ROLE_ADMIN: Literal["Admin"] = "Admin"
ROLE_USER: Literal["User"] = "User"

# Audit fields are ALWAYS appended.
CORE_HEADERS = [
    "created_at",  # UTC ISO timestamp
    "visit_date",
    "medical_unit",
    "patient_name",
    "national_id",
    "phone",
    "residence_area",
    "fp_status",
    "reason_non_use",
    "submitted_by",
    "role",
]

FP_STATUSES = ["مستخدمات طويل المدى", "مستخدمات قصير المدى", "لا تستخدم"]

# Can be replaced later with reference tables.
DEFAULT_MEDICAL_UNITS = ["وحدة 1", "وحدة 2", "وحدة 3"]
DEFAULT_AREAS = ["المنطقة 1", "المنطقة 2", "المنطقة 3"]

# Strict patterns
NATIONAL_ID_RE = re.compile(r"^\d{14}$")
PHONE_RE = re.compile(r"^01\d{9}$")  # 11 digits starting with 01


# ==========================
# UI (Medical White/Blue Theme)
# ==========================


def set_page() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="expanded")


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root{
          --bg: #f6fbff;
          --bg2: #eaf4ff;
          --card: rgba(255,255,255,0.90);
          --border: rgba(15, 23, 42, 0.10);
          --text: rgba(15, 23, 42, 0.94);
          --muted: rgba(15, 23, 42, 0.70);
          --shadow: 0 16px 40px rgba(2, 6, 23, 0.10);
          --accent: #2563eb;
          --accent2: #06b6d4;
        }

        .stApp{
          background:
            radial-gradient(1200px 520px at 15% 0%, rgba(37, 99, 235, 0.14), transparent 60%),
            radial-gradient(900px 520px at 90% 10%, rgba(6, 182, 212, 0.14), transparent 60%),
            linear-gradient(180deg, var(--bg), var(--bg2));
          color: var(--text);
        }

        section[data-testid="stSidebar"]{
          background: linear-gradient(180deg, rgba(255,255,255,0.93), rgba(255,255,255,0.80));
          border-right: 1px solid var(--border);
        }
        [data-testid="stSidebarNav"]{ display: none; }

        div[data-testid="stMetric"]{
          background: var(--card);
          border: 1px solid var(--border);
          border-radius: 16px;
          padding: 10px 14px;
          box-shadow: var(--shadow);
        }

        .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"]{
          background: rgba(255,255,255,0.94) !important;
          border: 1px solid rgba(15, 23, 42, 0.14) !important;
          border-radius: 12px !important;
        }
        .stButton > button{
          border-radius: 14px;
          border: 1px solid rgba(37, 99, 235, 0.18);
          background: linear-gradient(135deg, rgba(37, 99, 235, 0.95), rgba(6, 182, 212, 0.90));
          color: white;
          box-shadow: var(--shadow);
          padding: 0.55rem 1rem;
          font-weight: 700;
        }
        .stButton > button:hover{
          filter: brightness(1.05);
          border-color: rgba(37, 99, 235, 0.32);
        }

        /* Login Card */
        .login-wrap{
          min-height: calc(100vh - 120px);
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .login-card{
          width: min(520px, 92vw);
          background: rgba(255,255,255,0.92);
          border: 1px solid var(--border);
          border-radius: 20px;
          box-shadow: var(--shadow);
          padding: 22px 22px 12px 22px;
          animation: fadeUp 260ms ease-out;
          backdrop-filter: blur(8px);
        }
        @keyframes fadeUp{
          from{ transform: translateY(10px); opacity: 0.0; }
          to{ transform: translateY(0px); opacity: 1.0; }
        }
        .logo{
          width: 68px; height: 68px;
          border-radius: 18px;
          border: 1px dashed rgba(37, 99, 235, 0.35);
          display: flex; align-items: center; justify-content: center;
          color: rgba(37, 99, 235, 0.85);
          font-weight: 900;
          letter-spacing: 0.5px;
          margin: 0 auto 10px auto;
          background: rgba(37, 99, 235, 0.06);
        }
        .login-title{
          text-align: center;
          font-size: 1.25rem;
          font-weight: 900;
          margin: 4px 0 0 0;
        }
        .login-subtitle{
          text-align: center;
          color: var(--muted);
          margin: 6px 0 14px 0;
          font-size: 0.95rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==========================
# AUTH (RBAC: Admin/User)
# ==========================


@dataclass(frozen=True)
class User:
    username: str
    role: Literal["Admin", "User"]


def _require_auth_secrets() -> dict[str, dict[str, str]]:
    """
    Credentials MUST come from st.secrets only.

    Expected structure:

    [auth]
    users = [
      { username="admin", password="PUT_A_STRONG_PASSWORD_HERE", role="Admin" },
      { username="user1", password="PUT_A_STRONG_PASSWORD_HERE", role="User" },
    ]
    """
    auth_section = st.secrets.get("auth", None)
    if not auth_section or not isinstance(auth_section, dict):
        raise RuntimeError("Missing [auth] section.")

    raw_users = auth_section.get("users", [])
    if not isinstance(raw_users, list) or not raw_users:
        raise RuntimeError("Missing [auth].users list.")

    users: dict[str, dict[str, str]] = {}
    for u in raw_users:
        if not isinstance(u, dict):
            continue
        username = str(u.get("username", "")).strip()
        password = str(u.get("password", ""))
        role = str(u.get("role", ROLE_USER)).strip() or ROLE_USER
        if not username or not password:
            continue
        if role not in (ROLE_ADMIN, ROLE_USER):
            role = ROLE_USER
        users[username] = {"password": password, "role": role}

    if "admin" not in users or users["admin"].get("role") != ROLE_ADMIN:
        raise RuntimeError("Admin account must exist: username=admin and role=Admin.")

    return users


def verify_login(username: str, password: str) -> User | None:
    username = (username or "").strip()
    password = password or ""
    try:
        users = _require_auth_secrets()
    except Exception:
        return None
    if username not in users:
        return None
    if not hmac.compare_digest(password, users[username]["password"]):
        return None
    role = users[username].get("role", ROLE_USER) or ROLE_USER
    if role not in (ROLE_ADMIN, ROLE_USER):
        role = ROLE_USER
    return User(username=username, role=role)  # type: ignore[arg-type]


def logout() -> None:
    st.session_state.pop("user", None)
    st.session_state.pop("nav", None)


# ==========================
# GOOGLE SHEETS (append-only)
# ==========================


def _require_sheets_secrets() -> tuple[dict[str, Any], str]:
    if "gcp_service_account" not in st.secrets or "sheets" not in st.secrets:
        raise RuntimeError("Missing secrets: [gcp_service_account] and [sheets].")
    sa = dict(st.secrets["gcp_service_account"])
    spreadsheet_id = str(st.secrets["sheets"].get("spreadsheet_id", "")).strip()
    if not spreadsheet_id:
        raise RuntimeError("Missing [sheets].spreadsheet_id in secrets.toml.")
    return sa, spreadsheet_id


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    import gspread

    sa, spreadsheet_id = _require_sheets_secrets()
    client = gspread.service_account_from_dict(sa)
    return client.open_by_key(spreadsheet_id)


def safe_sheet_title(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return "untitled"
    banned = set(":\\/?*[]")
    cleaned = "".join("_" if ch in banned else ch for ch in n)
    cleaned = " ".join(cleaned.split())
    return cleaned[:100]


def _stringify(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


def get_or_create_worksheet(title: str, headers: list[str]):
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(title)
    except Exception:
        ws = ss.add_worksheet(title=title, rows=2000, cols=max(10, len(headers) + 2))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        return ws

    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []
    if not first_row and headers:
        ws.append_row(headers, value_input_option="USER_ENTERED")
    return ws


def append_row_to_worksheet(worksheet_title: str, headers: list[str], row: list[Any]) -> None:
    ws = get_or_create_worksheet(worksheet_title, headers=headers)
    ws.append_row([_stringify(v) for v in row], value_input_option="USER_ENTERED")


@st.cache_data(show_spinner=False, ttl=15)
def read_all_records(worksheet_title: str) -> list[dict[str, Any]]:
    ss = get_spreadsheet()
    ws = ss.worksheet(worksheet_title)
    return ws.get_all_records()


# ==========================
# DYNAMIC TABS (Builder + Manage)
# ==========================


@dataclass(frozen=True)
class DynamicField:
    name: str
    type: str  # "Text" | "Number" | "Dropdown"
    options: list[str] | None = None


@dataclass(frozen=True)
class DynamicTab:
    tab_name: str
    worksheet_title: str
    fields: list[DynamicField]


META_HEADERS = ["created_at", "tab_name", "worksheet_title", "schema_json"]


def _schema_to_json(fields: list[DynamicField], *, deleted: bool = False) -> str:
    """
    Backward compatible storage:
    - New: {"deleted": bool, "fields":[...]}
    - Old: [{"name":..,"type":..,"options":[...]}]
    """
    payload = {
        "deleted": bool(deleted),
        "fields": [{"name": f.name, "type": f.type, "options": f.options or []} for f in fields],
    }
    return json.dumps(payload, ensure_ascii=False)


def _schema_from_json(schema_json: str) -> tuple[bool, list[DynamicField]]:
    try:
        raw = json.loads(schema_json or "[]")
    except Exception:
        raw = []

    deleted = False
    if isinstance(raw, dict):
        deleted = bool(raw.get("deleted", False))
        raw = raw.get("fields", [])

    if not isinstance(raw, list):
        return deleted, []

    out: list[DynamicField] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        ftype = str(item.get("type", "Text")).strip()
        options = item.get("options", [])
        if not name:
            continue
        if ftype not in ("Text", "Number", "Dropdown"):
            ftype = "Text"
        opt_list: list[str] = []
        if ftype == "Dropdown" and isinstance(options, list):
            opt_list = [str(x).strip() for x in options if str(x).strip()]
        out.append(DynamicField(name=name, type=ftype, options=opt_list))
    return deleted, out


def save_tab_definition(tab_name: str, fields: list[DynamicField]) -> DynamicTab:
    tab_name = (tab_name or "").strip()
    worksheet_title = safe_sheet_title(f"tab_{tab_name}")
    append_row_to_worksheet(
        META_WORKSHEET,
        headers=META_HEADERS,
        row=[dt.datetime.utcnow().isoformat(), tab_name, worksheet_title, _schema_to_json(fields, deleted=False)],
    )
    return DynamicTab(tab_name=tab_name, worksheet_title=worksheet_title, fields=fields)


def update_tab_definition(tab_name: str, worksheet_title: str, fields: list[DynamicField]) -> None:
    append_row_to_worksheet(
        META_WORKSHEET,
        headers=META_HEADERS,
        row=[dt.datetime.utcnow().isoformat(), tab_name.strip(), worksheet_title, _schema_to_json(fields, deleted=False)],
    )


def delete_tab_definition(tab_name: str, worksheet_title: str) -> None:
    append_row_to_worksheet(
        META_WORKSHEET,
        headers=META_HEADERS,
        row=[dt.datetime.utcnow().isoformat(), tab_name.strip(), worksheet_title, _schema_to_json([], deleted=True)],
    )


def load_dynamic_tabs() -> list[DynamicTab]:
    try:
        rows = read_all_records(META_WORKSHEET)
    except Exception:
        return []

    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        name = str(r.get("tab_name", "")).strip()
        if name:
            latest[name] = r

    tabs: list[DynamicTab] = []
    for name, r in latest.items():
        ws_title = str(r.get("worksheet_title", "")).strip() or safe_sheet_title(f"tab_{name}")
        deleted, fields = _schema_from_json(str(r.get("schema_json", "") or "[]"))
        if deleted:
            continue
        if fields:
            tabs.append(DynamicTab(tab_name=name, worksheet_title=ws_title, fields=fields))
    tabs.sort(key=lambda t: t.tab_name.lower())
    return tabs


# ==========================
# VALIDATION (Strict)
# ==========================


def require_nonempty(label: str, value: Any) -> str | None:
    v = str(value or "").strip()
    if not v:
        return f"حقل ({label}) مطلوب."
    return None


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


# ==========================
# DASHBOARD (Plotly) + Export
# ==========================


def _parse_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def render_dashboard(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    st.subheader("لوحة المتابعة والتحليلات")

    if not records:
        st.info("لا توجد بيانات بعد. قم بإدخال بعض السجلات أولاً.")
        return []

    normalized: list[dict[str, Any]] = []
    for r in records:
        d = _parse_date(r.get("visit_date"))
        if not d:
            continue
        normalized.append(
            {
                "visit_date": d,
                "medical_unit": str(r.get("medical_unit", "")).strip() or "—",
                "fp_status": str(r.get("fp_status", "")).strip() or "—",
                "submitted_by": str(r.get("submitted_by", "")).strip(),
                "created_at": str(r.get("created_at", "")).strip(),
            }
        )

    if not normalized:
        st.info("لا توجد سجلات بتاريخ صحيح حتى الآن.")
        return []

    today = dt.date.today()
    total_all = len(normalized)
    total_today = sum(1 for r in normalized if r["visit_date"] == today)
    fp_non_use = sum(1 for r in normalized if r.get("fp_status") == "لا تستخدم")
    unit_count = len({r.get("medical_unit") for r in normalized if r.get("medical_unit")})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("إجمالي السجلات", f"{total_all:,}")
    c2.metric("سجلات اليوم", f"{total_today:,}")
    c3.metric("لا تستخدم", f"{fp_non_use:,}")
    c4.metric("عدد الوحدات", f"{unit_count:,}")

    with st.expander("مرشّحات", expanded=True):
        min_d = min(r["visit_date"] for r in normalized)
        max_d = max(r["visit_date"] for r in normalized)
        dr = st.date_input("الفترة الزمنية", value=(min_d, max_d))
        unit_options = ["الكل"] + sorted({r["medical_unit"] for r in normalized if r["medical_unit"]})
        unit = st.selectbox("الوحدة الطبية", unit_options, index=0)

    if isinstance(dr, tuple) and len(dr) == 2:
        start, end = dr
        filtered = [r for r in normalized if start <= r["visit_date"] <= end]
    else:
        filtered = list(normalized)
    if unit != "الكل":
        filtered = [r for r in filtered if r.get("medical_unit") == unit]

    st.divider()

    left, right = st.columns([1.2, 1])

    with left:
        units = sorted({r.get("medical_unit") or "—" for r in filtered})
        by_unit_day: dict[str, dict[dt.date, int]] = {u: defaultdict(int) for u in units}
        for r in filtered:
            by_unit_day[r.get("medical_unit") or "—"][r["visit_date"]] += 1
        all_days = sorted({r["visit_date"] for r in filtered})

        fig = go.Figure()
        for u in units:
            ys = [by_unit_day[u].get(d, 0) for d in all_days]
            fig.add_trace(go.Scatter(x=all_days, y=ys, mode="lines+markers", name=u))
        fig.update_layout(
            title="اتجاه الإدخالات اليومية حسب الوحدة",
            height=360,
            margin=dict(l=10, r=10, t=60, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        counts = Counter([r.get("fp_status") or "—" for r in filtered])
        fig2 = go.Figure(data=[go.Pie(labels=list(counts.keys()), values=list(counts.values()), hole=0.35)])
        fig2.update_layout(title="حالة تنظيم الأسرة", height=360, margin=dict(l=10, r=10, t=60, b=10))
        st.plotly_chart(fig2, use_container_width=True)

    unit_counts = Counter([r.get("medical_unit") or "—" for r in filtered])
    fig3 = go.Figure(data=[go.Bar(x=list(unit_counts.keys()), y=list(unit_counts.values()))])
    fig3.update_layout(title="عدد الإدخالات لكل وحدة", height=380, margin=dict(l=10, r=10, t=60, b=10))
    st.plotly_chart(fig3, use_container_width=True)

    return filtered


def _records_to_excel_bytes(records: list[dict[str, Any]], *, sheet_name: str = "Report") -> bytes:
    import pandas as pd

    df = pd.DataFrame(records)
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return out.getvalue()


def _records_to_pdf_bytes(records: list[dict[str, Any]], *, title: str) -> bytes | None:
    """
    Best-effort PDF export using reportlab if available.
    Returns None if reportlab isn't installed.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception:
        return None

    headers: list[str] = list(records[0].keys()) if records else []
    rows: list[list[str]] = [headers]
    for r in records[:2000]:
        rows.append([_stringify(r.get(h, "")) for h in headers])

    buff = BytesIO()
    doc = SimpleDocTemplate(buff, pagesize=A4, title=title)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 10)]

    tbl = Table(rows, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#94a3b8")),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ]
        )
    )
    story.append(tbl)
    doc.build(story)
    return buff.getvalue()


# ==========================
# NAVIGATION (option_menu if available)
# ==========================


def _option_menu_available() -> bool:
    try:
        import streamlit_option_menu  # noqa: F401

        return True
    except Exception:
        return False


def sidebar_nav(role: str, dynamic_tabs: list[DynamicTab]) -> str:
    with st.sidebar:
        st.markdown("### التنقّل")

        options: list[str] = ["📝 إدخال البيانات"]
        icons: list[str] = ["clipboard2-pulse"]

        if role == ROLE_ADMIN:
            options += ["📊 لوحة المتابعة", "➕ منشئ التبويبات"]
            icons += ["bar-chart-line", "layers"]

        if dynamic_tabs:
            st.caption("نماذج إضافية")
            for t in dynamic_tabs:
                options.append(f"🧩 {t.tab_name}")
                icons.append("ui-checks")

        current = st.session_state.get("nav", "📝 إدخال البيانات")
        if current not in options:
            current = "📝 إدخال البيانات"

        if _option_menu_available():
            from streamlit_option_menu import option_menu

            nav = option_menu(
                menu_title=None,
                options=options,
                icons=icons[: len(options)],
                default_index=options.index(current),
                styles={
                    "container": {"padding": "0!important", "background-color": "rgba(255,255,255,0.0)"},
                    "icon": {"color": "#2563eb", "font-size": "18px"},
                    "nav-link": {"font-size": "16px", "text-align": "right", "margin": "0px", "border-radius": "12px"},
                    "nav-link-selected": {"background-color": "rgba(37, 99, 235, 0.12)"},
                },
            )
        else:
            nav = st.radio("اذهب إلى", options, index=options.index(current))

        st.divider()
        st.caption(f"المستخدم: **{st.session_state['user']['username']}**")
        st.caption(f"الصلاحية: **{role}**")
        if st.button("تسجيل الخروج"):
            logout()
            st.rerun()

    return nav


# ==========================
# PAGES
# ==========================


def _init_state() -> None:
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("nav", "📝 إدخال البيانات")
    st.session_state.setdefault("tab_builder_fields", [])
    st.session_state.setdefault("edit_tab_target", None)


def login_view() -> None:
    st.markdown('<div class="login-wrap"><div class="login-card">', unsafe_allow_html=True)
    st.markdown('<div class="logo">LOGO</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="login-title">{APP_TITLE}</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-subtitle">تسجيل الدخول للوصول إلى النظام</div>', unsafe_allow_html=True)

    auth_ok = True
    try:
        _ = _require_auth_secrets()
    except Exception:
        auth_ok = False

    if not auth_ok:
        st.warning("لم يتم إعداد حسابات الدخول بعد. يرجى تحديث ملف secrets.toml (قسم auth).")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("اسم المستخدم", value="", placeholder="admin")
        password = st.text_input("كلمة المرور", type="password", value="", placeholder="••••••••")
        submitted = st.form_submit_button("دخول")

    st.markdown("</div></div>", unsafe_allow_html=True)

    if not submitted:
        return
    u = verify_login(username=username, password=password)
    if not u:
        st.error("اسم المستخدم أو كلمة المرور غير صحيحة.")
        return
    st.session_state["user"] = {"username": u.username, "role": u.role}
    st.session_state["nav"] = "📝 إدخال البيانات"
    st.toast(f"مرحباً {u.username}")
    st.rerun()


def validate_core_form(
    visit_date: dt.date,
    medical_unit: str,
    patient_name: str,
    national_id: str,
    phone: str,
    residence_area: str,
    fp_status: str,
    reason_non_use: str,
) -> list[str]:
    errors: list[str] = []
    for label, value in [
        ("تاريخ الزيارة", visit_date.isoformat() if visit_date else ""),
        ("اسم الوحدة الطبية", medical_unit),
        ("اسم السيدة", patient_name),
        ("منطقة السكن", residence_area),
        ("حالة تنظيم الأسرة", fp_status),
    ]:
        err = require_nonempty(label, value)
        if err:
            errors.append(err)

    nid_err = validate_national_id(national_id)
    if nid_err:
        errors.append(nid_err)

    phone_err = validate_phone(phone)
    if phone_err:
        errors.append(phone_err)

    if fp_status == "لا تستخدم":
        err = require_nonempty("سبب عدم الاستخدام", reason_non_use)
        if err:
            errors.append(err)

    return errors


def core_form_view(user: dict[str, str]) -> None:
    st.subheader("📝 إدخال البيانات الأساسية")

    with st.form("core_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            visit_date = st.date_input("تاريخ الزيارة", value=dt.date.today())
        with c2:
            medical_unit = st.selectbox("اسم الوحدة الطبية", DEFAULT_MEDICAL_UNITS, index=0)
        with c3:
            residence_area = st.selectbox("منطقة السكن", DEFAULT_AREAS, index=0)

        c4, c5, c6 = st.columns(3)
        with c4:
            patient_name = st.text_input("اسم السيدة")
        with c5:
            national_id = st.text_input("الرقم القومي (14 رقم)", placeholder="xxxxxxxxxxxxxx")
        with c6:
            phone = st.text_input("رقم الهاتف (11 رقم ويبدأ بـ 01)", placeholder="01xxxxxxxxx")

        fp_status = st.selectbox("حالة تنظيم الأسرة", FP_STATUSES, index=0)
        reason_non_use = ""
        if fp_status == "لا تستخدم":
            reason_non_use = st.text_input("سبب عدم الاستخدام (إجباري)")

        submitted = st.form_submit_button("حفظ")

    if not submitted:
        return

    errors = validate_core_form(
        visit_date=visit_date,
        medical_unit=medical_unit,
        patient_name=patient_name,
        national_id=national_id,
        phone=phone,
        residence_area=residence_area,
        fp_status=fp_status,
        reason_non_use=reason_non_use,
    )
    if errors:
        st.markdown("### يرجى مراجعة التالي")
        for e in errors:
            st.warning(e)
        return

    row = [
        dt.datetime.utcnow().isoformat(),
        visit_date,
        medical_unit.strip(),
        patient_name.strip(),
        national_id.strip(),
        phone.strip(),
        residence_area.strip(),
        fp_status.strip(),
        (reason_non_use or "").strip(),
        user["username"],
        user["role"],
    ]

    try:
        append_row_to_worksheet(CORE_WORKSHEET, headers=CORE_HEADERS, row=row)
        st.toast("تم الحفظ بنجاح.")
        read_all_records.clear()
    except Exception as e:
        st.error(f"تعذر الحفظ على Google Sheets: {e}")


def _clean_dynamic_fields(raw_fields: Iterable[dict[str, Any]]) -> list[DynamicField]:
    cleaned: list[DynamicField] = []
    for f in raw_fields:
        if f.get("_remove"):
            continue
        name = str(f.get("name", "")).strip()
        ftype = str(f.get("type", "Text")).strip()
        if not name:
            continue
        if ftype not in ("Text", "Number", "Dropdown"):
            ftype = "Text"
        options: list[str] = []
        if ftype == "Dropdown":
            options = [x.strip() for x in str(f.get("options", "")).split(",") if x.strip()]
        cleaned.append(DynamicField(name=name, type=ftype, options=options))
    return cleaned


def tab_builder_view(dynamic_tabs: list[DynamicTab]) -> None:
    st.subheader("➕ منشئ التبويبات (للمسؤول فقط)")
    st.caption("إنشاء/تعديل نماذج إدخال إضافية. الحذف هنا حذف منطقي (Soft Delete) للحفاظ على السجل.")

    edit_target = st.session_state.get("edit_tab_target")
    target_tab = next((t for t in dynamic_tabs if t.tab_name == edit_target), None) if edit_target else None

    if target_tab:
        st.markdown(f"#### تعديل التبويب: **{target_tab.tab_name}**")
        tab_name_default = target_tab.tab_name
        fields_state = [{"name": f.name, "type": f.type, "options": ",".join(f.options or [])} for f in target_tab.fields]
    else:
        st.markdown("#### إنشاء تبويب جديد")
        tab_name_default = ""
        fields_state = st.session_state.get("tab_builder_fields", []) or [{"name": "", "type": "Text", "options": ""}]

    with st.form("tab_builder_form", clear_on_submit=False):
        tab_name = st.text_input("اسم التبويب", value=tab_name_default, placeholder="مثال: إحالات / تطعيمات")
        st.markdown("##### الحقول")

        for i, f in enumerate(fields_state):
            cc1, cc2, cc3, cc4 = st.columns([1.2, 0.9, 1.6, 0.6])
            with cc1:
                f["name"] = st.text_input(f"اسم الحقل #{i+1}", value=f.get("name", ""), key=f"tb_name_{i}")
            with cc2:
                f["type"] = st.selectbox(
                    f"النوع #{i+1}",
                    ["Text", "Number", "Dropdown"],
                    index=["Text", "Number", "Dropdown"].index(f.get("type", "Text")),
                    key=f"tb_type_{i}",
                )
            with cc3:
                if f["type"] == "Dropdown":
                    f["options"] = st.text_input(
                        f"خيارات القائمة #{i+1} (مفصولة بفواصل)",
                        value=f.get("options", ""),
                        key=f"tb_opt_{i}",
                    )
                else:
                    f["options"] = ""
                    st.text_input(
                        f"خيارات القائمة #{i+1} (مفصولة بفواصل)",
                        value="(غير مستخدم)",
                        disabled=True,
                        key=f"tb_opt_disabled_{i}",
                    )
            with cc4:
                f["_remove"] = st.checkbox("حذف", key=f"tb_rm_{i}")

        add_field = st.form_submit_button("➕ إضافة حقل")
        save = st.form_submit_button("💾 حفظ")

    if add_field:
        fields_state.append({"name": "", "type": "Text", "options": ""})
        st.session_state["tab_builder_fields"] = fields_state
        st.rerun()

    st.session_state["tab_builder_fields"] = fields_state

    if save:
        cleaned = _clean_dynamic_fields(fields_state)
        if not tab_name.strip():
            st.error("اسم التبويب مطلوب.")
            return
        if not cleaned:
            st.error("أضف حقل واحد على الأقل.")
            return

        try:
            if target_tab:
                update_tab_definition(tab_name=tab_name.strip(), worksheet_title=target_tab.worksheet_title, fields=cleaned)
                st.success("تم تحديث التبويب بنجاح.")
                st.session_state["edit_tab_target"] = None
            else:
                save_tab_definition(tab_name=tab_name.strip(), fields=cleaned)
                st.success("تم إنشاء التبويب بنجاح.")

            read_all_records.clear()
            st.session_state["tab_builder_fields"] = [{"name": "", "type": "Text", "options": ""}]
            st.rerun()
        except Exception as e:
            st.error(f"تعذر حفظ تعريف التبويب: {e}")

    st.divider()
    st.markdown("#### إدارة التبويبات الحالية")
    if not dynamic_tabs:
        st.info("لا توجد تبويبات إضافية حالياً.")
        return

    for t in dynamic_tabs:
        cols = st.columns([1.8, 1, 1])
        cols[0].markdown(f"**{t.tab_name}**  \n`{t.worksheet_title}`")
        if cols[1].button("✏️ تعديل", key=f"edit_{t.tab_name}"):
            st.session_state["edit_tab_target"] = t.tab_name
            st.rerun()
        if cols[2].button("🗑️ حذف", key=f"del_{t.tab_name}"):
            st.session_state[f"confirm_del_{t.tab_name}"] = True
            st.rerun()

        if st.session_state.get(f"confirm_del_{t.tab_name}", False):
            c2 = st.columns([1.8, 1, 1])
            c2[0].warning("تأكيد حذف التبويب؟ (لن يتم حذف البيانات القديمة من الشيت)")
            if c2[1].button("تأكيد", key=f"do_del_{t.tab_name}"):
                try:
                    delete_tab_definition(tab_name=t.tab_name, worksheet_title=t.worksheet_title)
                    read_all_records.clear()
                    st.session_state.pop(f"confirm_del_{t.tab_name}", None)
                    st.success("تم حذف التبويب (حذف منطقي).")
                    st.rerun()
                except Exception as e:
                    st.error(f"تعذر حذف التبويب: {e}")
            if c2[2].button("إلغاء", key=f"cancel_del_{t.tab_name}"):
                st.session_state.pop(f"confirm_del_{t.tab_name}", None)
                st.rerun()


def dynamic_tab_view(tab: DynamicTab, user: dict[str, str]) -> None:
    st.subheader(f"🧩 نموذج إضافي — {tab.tab_name}")

    headers = ["created_at"] + [f.name for f in tab.fields] + ["submitted_by", "role"]

    with st.form(f"dyn_{tab.worksheet_title}", clear_on_submit=True):
        values: dict[str, Any] = {}
        for f in tab.fields:
            if f.type == "Text":
                values[f.name] = st.text_input(f.name)
            elif f.type == "Number":
                values[f.name] = st.number_input(f.name, step=1.0)
            else:
                opts = f.options or []
                values[f.name] = st.selectbox(f.name, opts if opts else [""])
        submitted = st.form_submit_button("حفظ")

    if not submitted:
        return

    errs: list[str] = []
    for f in tab.fields:
        v = values.get(f.name, "")
        if f.type == "Number":
            if v is None:
                errs.append(f"حقل ({f.name}) مطلوب.")
        else:
            if not str(v).strip():
                errs.append(f"حقل ({f.name}) مطلوب.")
    if errs:
        for e in errs:
            st.warning(e)
        return

    row = [dt.datetime.utcnow().isoformat()] + [values.get(f.name, "") for f in tab.fields] + [user["username"], user["role"]]
    try:
        append_row_to_worksheet(tab.worksheet_title, headers=headers, row=row)
        st.toast("تم الحفظ بنجاح.")
        read_all_records.clear()
    except Exception as e:
        st.error(f"تعذر الحفظ على Google Sheets: {e}")


def dashboard_view(*, allow_export: bool) -> None:
    try:
        records = read_all_records(CORE_WORKSHEET)
    except Exception as e:
        st.error(f"تعذر قراءة بيانات الشيت `{CORE_WORKSHEET}`: {e}")
        return

    filtered = render_dashboard(records)
    if not allow_export:
        return

    st.divider()
    st.markdown("### التصدير (للمسؤول)")
    c1, c2 = st.columns([1, 1])

    with c1:
        try:
            excel_bytes = _records_to_excel_bytes(filtered, sheet_name="Medical Report")
            st.download_button(
                "⬇️ تنزيل Excel",
                data=excel_bytes,
                file_name=f"medical_report_{dt.date.today().isoformat()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.error(f"تعذر إنشاء تقرير Excel: {e}")

    with c2:
        pdf_bytes = _records_to_pdf_bytes(filtered, title="Medical Report")
        if pdf_bytes is None:
            st.info("تصدير PDF غير متاح حالياً (يتطلب تثبيت reportlab).")
        else:
            st.download_button(
                "⬇️ تنزيل PDF",
                data=pdf_bytes,
                file_name=f"medical_report_{dt.date.today().isoformat()}.pdf",
                mime="application/pdf",
            )


# ==========================
# APP ENTRY
# ==========================


def main() -> None:
    set_page()
    inject_css()
    _init_state()

    if not st.session_state.get("user"):
        login_view()
        return

    user = st.session_state["user"]
    role = user["role"]

    st.title(APP_TITLE)

    try:
        dynamic_tabs = load_dynamic_tabs()
    except Exception:
        dynamic_tabs = []

    nav = sidebar_nav(role=role, dynamic_tabs=dynamic_tabs)
    st.session_state["nav"] = nav

    # RBAC enforcement:
    # - Admin: full access
    # - User: data entry only (no dashboard, no tab builder, no admin controls)
    if nav == "📝 إدخال البيانات":
        core_form_view(user=user)
        return

    if nav == "📊 لوحة المتابعة":
        if role != ROLE_ADMIN:
            st.error("هذه الصفحة متاحة للمسؤول فقط.")
            return
        dashboard_view(allow_export=True)
        return

    if nav == "➕ منشئ التبويبات":
        if role != ROLE_ADMIN:
            st.error("هذه الصفحة متاحة للمسؤول فقط.")
            return
        tab_builder_view(dynamic_tabs=dynamic_tabs)
        return

    if nav.startswith("🧩 "):
        name = nav.replace("🧩 ", "", 1).strip()
        tab = next((t for t in dynamic_tabs if t.tab_name == name), None)
        if not tab:
            st.error("هذا التبويب غير موجود حالياً.")
            return
        dynamic_tab_view(tab=tab, user=user)
        return

    st.info("اختر صفحة من القائمة الجانبية.")


if __name__ == "__main__":
    main()

from __future__ import annotations

import datetime as dt
import hmac
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import plotly.graph_objects as go
import streamlit as st

# ==========================
# CONFIG + CONSTANTS
# ==========================

APP_TITLE = "Medical Health Units – Data Collection"

CORE_WORKSHEET = "core_visits"
META_WORKSHEET = "_meta_tabs"  # stores dynamic tab definitions (append-only)

CORE_HEADERS = [
    "created_at",
    "visit_date",
    "medical_unit",
    "patient_name",
    "national_id",
    "phone",
    "residence_area",
    "fp_status",
    "reason_non_use",
    "submitted_by",
    "role",
]

FP_STATUSES = ["مستخدمات طويل المدى", "مستخدمات قصير المدى", "لا تستخدم"]

# You can replace these with values loaded from CSVs later.
DEFAULT_MEDICAL_UNITS = ["وحدة 1", "وحدة 2", "وحدة 3"]
DEFAULT_AREAS = ["المنطقة 1", "المنطقة 2", "المنطقة 3"]

NATIONAL_ID_RE = re.compile(r"^\d{14}$")
PHONE_RE = re.compile(r"^01\d{9}$")


# ==========================
# UI (Modern CSS)
# ==========================

def set_page() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="expanded")


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root{
          --bg: #f6fbff;
          --bg2: #eaf4ff;
          --card: rgba(255,255,255,0.85);
          --border: rgba(15, 23, 42, 0.10);
          --text: rgba(15, 23, 42, 0.94);
          --muted: rgba(15, 23, 42, 0.70);
          --shadow: 0 16px 40px rgba(2, 6, 23, 0.10);
          --accent: #2563eb;
          --accent2: #06b6d4;
        }

        .stApp{
          background:
            radial-gradient(1200px 520px at 15% 0%, rgba(37, 99, 235, 0.14), transparent 60%),
            radial-gradient(900px 520px at 90% 10%, rgba(6, 182, 212, 0.14), transparent 60%),
            linear-gradient(180deg, var(--bg), var(--bg2));
          color: var(--text);
        }
        section[data-testid="stSidebar"]{
          background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.78));
          border-right: 1px solid var(--border);
        }
        div[data-testid="stMetric"]{
          background: var(--card);
          border: 1px solid var(--border);
          border-radius: 16px;
          padding: 10px 14px;
          box-shadow: var(--shadow);
        }
        .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"]{
          background: rgba(255,255,255,0.92) !important;
          border: 1px solid rgba(15, 23, 42, 0.14) !important;
          border-radius: 12px !important;
        }
        .stButton > button{
          border-radius: 14px;
          border: 1px solid rgba(37, 99, 235, 0.18);
          background: linear-gradient(135deg, rgba(37, 99, 235, 0.95), rgba(6, 182, 212, 0.90));
          color: white;
          box-shadow: var(--shadow);
          padding: 0.55rem 1rem;
          font-weight: 650;
        }
        .stButton > button:hover{
          filter: brightness(1.05);
          border-color: rgba(37, 99, 235, 0.32);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==========================
# AUTH (Admin / Data Entry)
# ==========================

@dataclass(frozen=True)
class User:
    username: str
    role: str  # "Admin" | "Data Entry"


def get_users() -> dict[str, dict[str, str]]:
    # Default test credentials per your request:
    users = {"admin": {"password": "admin123", "role": "Admin"}}

    # Optional extra users from secrets.toml:
    # [auth]
    # users = [{username="u", password="p", role="Data Entry"}]
    auth_section = st.secrets.get("auth", None)
    if auth_section and isinstance(auth_section, dict):
        raw_users = auth_section.get("users", [])
        if isinstance(raw_users, list):
            for u in raw_users:
                if not isinstance(u, dict):
                    continue
                username = str(u.get("username", "")).strip()
                password = str(u.get("password", ""))
                role = str(u.get("role", "Data Entry")).strip() or "Data Entry"
                if username:
                    users[username] = {"password": password, "role": role}
    return users


def verify_login(username: str, password: str) -> User | None:
    username = (username or "").strip()
    password = password or ""
    users = get_users()
    if username not in users:
        return None
    if not hmac.compare_digest(password, users[username]["password"]):
        return None
    role = users[username].get("role", "Data Entry") or "Data Entry"
    if role not in ("Admin", "Data Entry"):
        role = "Data Entry"
    return User(username=username, role=role)


def logout() -> None:
    st.session_state.pop("user", None)
    st.session_state.pop("nav", None)


# ==========================
# GOOGLE SHEETS (gspread) — append_row only
# ==========================

def _require_secrets() -> tuple[dict[str, Any], str]:
    if "gcp_service_account" not in st.secrets or "sheets" not in st.secrets:
        raise RuntimeError("Missing secrets. Need [gcp_service_account] and [sheets] in .streamlit/secrets.toml.")
    sa = dict(st.secrets["gcp_service_account"])
    spreadsheet_id = str(st.secrets["sheets"].get("spreadsheet_id", "")).strip()
    if not spreadsheet_id:
        raise RuntimeError("Missing [sheets].spreadsheet_id in .streamlit/secrets.toml.")
    return sa, spreadsheet_id


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    # Import lazily (more robust on some Windows setups)
    import gspread

    sa, spreadsheet_id = _require_secrets()
    client = gspread.service_account_from_dict(sa)
    return client.open_by_key(spreadsheet_id)


def safe_sheet_title(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return "untitled"
    banned = set(":\\/?*[]")
    cleaned = "".join("_" if ch in banned else ch for ch in n)
    cleaned = " ".join(cleaned.split())
    return cleaned[:100]


def _stringify(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


def get_or_create_worksheet(title: str, headers: list[str]):
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(title)
    except Exception:
        ws = ss.add_worksheet(title=title, rows=2000, cols=max(10, len(headers) + 2))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        return ws

    # Ensure a header row exists
    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []
    if not first_row and headers:
        ws.append_row(headers, value_input_option="USER_ENTERED")
    return ws


def append_row_to_worksheet(worksheet_title: str, headers: list[str], row: list[Any]) -> None:
    # Concurrency safety requirement: ALWAYS append_row
    ws = get_or_create_worksheet(worksheet_title, headers=headers)
    ws.append_row([_stringify(v) for v in row], value_input_option="USER_ENTERED")


@st.cache_data(show_spinner=False, ttl=15)
def read_all_records(worksheet_title: str) -> list[dict[str, Any]]:
    ss = get_spreadsheet()
    ws = ss.worksheet(worksheet_title)
    return ws.get_all_records()


# ==========================
# DYNAMIC TABS (Admin “+” builder)
# ==========================

@dataclass(frozen=True)
class DynamicField:
    name: str
    type: str  # "Text" | "Number" | "Dropdown"
    options: list[str] | None = None


@dataclass(frozen=True)
class DynamicTab:
    tab_name: str
    worksheet_title: str
    fields: list[DynamicField]


META_HEADERS = ["created_at", "tab_name", "worksheet_title", "schema_json"]


def _schema_to_json(fields: list[DynamicField]) -> str:
    payload = [{"name": f.name, "type": f.type, "options": f.options or []} for f in fields]
    return json.dumps(payload, ensure_ascii=False)


def _schema_from_json(schema_json: str) -> list[DynamicField]:
    try:
        raw = json.loads(schema_json or "[]")
    except Exception:
        raw = []
    if not isinstance(raw, list):
        return []
    out: list[DynamicField] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        ftype = str(item.get("type", "Text")).strip()
        options = item.get("options", [])
        if not name:
            continue
        if ftype not in ("Text", "Number", "Dropdown"):
            ftype = "Text"
        opt_list: list[str] = []
        if ftype == "Dropdown":
            if isinstance(options, list):
                opt_list = [str(x).strip() for x in options if str(x).strip()]
        out.append(DynamicField(name=name, type=ftype, options=opt_list))
    return out


def save_tab_definition(tab_name: str, fields: list[DynamicField]) -> DynamicTab:
    tab_name = (tab_name or "").strip()
    worksheet_title = safe_sheet_title(f"tab_{tab_name}")
    append_row_to_worksheet(
        META_WORKSHEET,
        headers=META_HEADERS,
        row=[dt.datetime.utcnow().isoformat(), tab_name, worksheet_title, _schema_to_json(fields)],
    )
    return DynamicTab(tab_name=tab_name, worksheet_title=worksheet_title, fields=fields)


def load_dynamic_tabs() -> list[DynamicTab]:
    try:
        rows = read_all_records(META_WORKSHEET)
    except Exception:
        return []

    # last definition wins (append-only storage)
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        name = str(r.get("tab_name", "")).strip()
        if name:
            latest[name] = r

    tabs: list[DynamicTab] = []
    for name, r in latest.items():
        ws_title = str(r.get("worksheet_title", "")).strip() or safe_sheet_title(f"tab_{name}")
        fields = _schema_from_json(str(r.get("schema_json", "") or "[]"))
        if fields:
            tabs.append(DynamicTab(tab_name=name, worksheet_title=ws_title, fields=fields))
    tabs.sort(key=lambda t: t.tab_name.lower())
    return tabs


# ==========================
# VALIDATION (Strict)
# ==========================

def require_nonempty(label: str, value: Any) -> str | None:
    v = str(value or "").strip()
    if not v:
        return f"حقل ({label}) مطلوب."
    return None


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


# ==========================
# DASHBOARD (Plotly)
# ==========================

def _parse_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def render_dashboard(records: list[dict[str, Any]]) -> None:
    st.subheader("Analytics Dashboard")

    if not records:
        st.info("No data yet. Submit some records first.")
        return

    normalized = []
    for r in records:
        d = _parse_date(r.get("visit_date"))
        if not d:
            continue
        normalized.append(
            {
                "visit_date": d,
                "medical_unit": str(r.get("medical_unit", "")).strip(),
                "fp_status": str(r.get("fp_status", "")).strip(),
            }
        )
    if not normalized:
        st.info("No valid-dated rows found yet.")
        return

    today = dt.date.today()
    total_all = len(normalized)
    total_today = sum(1 for r in normalized if r["visit_date"] == today)
    fp_non_use = sum(1 for r in normalized if r.get("fp_status") == "لا تستخدم")
    unit_count = len({r.get("medical_unit") for r in normalized if r.get("medical_unit")})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Visits (All)", f"{total_all:,}")
    c2.metric("Total Visits (Today)", f"{total_today:,}")
    c3.metric("Non-use (لا تستخدم)", f"{fp_non_use:,}")
    c4.metric("Units (Distinct)", f"{unit_count:,}")

    with st.expander("Filters", expanded=True):
        min_d = min(r["visit_date"] for r in normalized)
        max_d = max(r["visit_date"] for r in normalized)
        dr = st.date_input("Date range", value=(min_d, max_d))
        unit_options = ["All"] + sorted({r["medical_unit"] for r in normalized if r["medical_unit"]})
        unit = st.selectbox("Medical Unit", unit_options, index=0)

    if isinstance(dr, tuple) and len(dr) == 2:
        start, end = dr
        filtered = [r for r in normalized if start <= r["visit_date"] <= end]
    else:
        filtered = list(normalized)
    if unit != "All":
        filtered = [r for r in filtered if r.get("medical_unit") == unit]

    st.divider()

    left, right = st.columns([1.2, 1])

    with left:
        by_day = defaultdict(int)
        for r in filtered:
            by_day[r["visit_date"]] += 1
        xs = sorted(by_day.keys())
        ys = [by_day[x] for x in xs]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name="Visits"))
        fig.update_layout(title="Daily Visits Trend", height=360, margin=dict(l=10, r=10, t=60, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with right:
        counts = Counter([r.get("fp_status") or "—" for r in filtered])
        fig2 = go.Figure(data=[go.Pie(labels=list(counts.keys()), values=list(counts.values()), hole=0.35)])
        fig2.update_layout(title="Family Planning Status", height=360, margin=dict(l=10, r=10, t=60, b=10))
        st.plotly_chart(fig2, use_container_width=True)

    unit_counts = Counter([r.get("medical_unit") or "—" for r in filtered])
    fig3 = go.Figure(data=[go.Bar(x=list(unit_counts.keys()), y=list(unit_counts.values()))])
    fig3.update_layout(title="Visits per Medical Unit", height=380, margin=dict(l=10, r=10, t=60, b=10))
    st.plotly_chart(fig3, use_container_width=True)


# ==========================
# PAGES (Login / Core / Builder / Dynamic / Dashboard)
# ==========================

def _init_state() -> None:
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("nav", "Core Form")
    st.session_state.setdefault("tab_builder_fields", [])


def login_view() -> None:
    st.title("Login")
    st.caption("Test admin: `admin / admin123`.")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", value="", placeholder="admin")
        password = st.text_input("Password", type="password", value="", placeholder="admin123")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        u = verify_login(username=username, password=password)
        if not u:
            st.error("Invalid username or password.")
            return
        st.session_state["user"] = {"username": u.username, "role": u.role}
        st.session_state["nav"] = "Core Form"
        st.toast(f"Welcome {u.username} ({u.role})")
        st.rerun()


def sidebar_nav(role: str, dynamic_tabs: list[DynamicTab]) -> str:
    with st.sidebar:
        st.subheader("Navigation")
        options = ["Core Form"]
        if role == "Admin":
            options += ["Dashboard", "+ Tab Builder"]
        if dynamic_tabs:
            st.caption("Dynamic Forms")
            options += [f"🧩 {t.tab_name}" for t in dynamic_tabs]

        current = st.session_state.get("nav", "Core Form")
        if current not in options:
            current = "Core Form"
        nav = st.radio("Go to", options, index=options.index(current))

        st.divider()
        st.caption(f"Signed in as: **{st.session_state['user']['username']}**")
        st.caption(f"Role: **{role}**")
        if st.button("Logout"):
            logout()
            st.rerun()
    return nav


def validate_core_form(
    visit_date: dt.date,
    medical_unit: str,
    patient_name: str,
    national_id: str,
    phone: str,
    residence_area: str,
    fp_status: str,
    reason_non_use: str,
) -> list[str]:
    errors: list[str] = []
    for label, value in [
        ("Date of Visit", visit_date.isoformat() if visit_date else ""),
        ("Medical Unit Name", medical_unit),
        ("Patient Name", patient_name),
        ("Residence Area", residence_area),
        ("Family Planning Status", fp_status),
    ]:
        err = require_nonempty(label, value)
        if err:
            errors.append(err)

    nid_err = validate_national_id(national_id)
    if nid_err:
        errors.append(nid_err)
    phone_err = validate_phone(phone)
    if phone_err:
        errors.append(phone_err)

    if fp_status == "لا تستخدم":
        err = require_nonempty("Reason for non-use", reason_non_use)
        if err:
            errors.append(err)
    return errors


def core_form_view(user: dict[str, str]) -> None:
    st.subheader("TAB 1 — Core Medical Form")

    with st.form("core_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            visit_date = st.date_input("Date of Visit", value=dt.date.today())
        with c2:
            medical_unit = st.selectbox("Medical Unit Name", DEFAULT_MEDICAL_UNITS, index=0)
        with c3:
            residence_area = st.selectbox("Residence Area", DEFAULT_AREAS, index=0)

        c4, c5, c6 = st.columns(3)
        with c4:
            patient_name = st.text_input("Patient Name")
        with c5:
            national_id = st.text_input("National ID (14 digits)", placeholder="xxxxxxxxxxxxxx")
        with c6:
            phone = st.text_input("Phone Number (11 digits, starts with 01)", placeholder="01xxxxxxxxx")

        fp_status = st.selectbox("Family Planning Status", FP_STATUSES, index=0)
        reason_non_use = ""
        if fp_status == "لا تستخدم":
            reason_non_use = st.text_input("Reason for non-use (required)")

        submitted = st.form_submit_button("Submit")

    if not submitted:
        return

    errors = validate_core_form(
        visit_date=visit_date,
        medical_unit=medical_unit,
        patient_name=patient_name,
        national_id=national_id,
        phone=phone,
        residence_area=residence_area,
        fp_status=fp_status,
        reason_non_use=reason_non_use,
    )
    if errors:
        st.markdown("### Please fix the following")
        for e in errors:
            st.warning(e)
        return

    row = [
        dt.datetime.utcnow().isoformat(),
        visit_date,
        medical_unit.strip(),
        patient_name.strip(),
        national_id.strip(),
        phone.strip(),
        residence_area.strip(),
        fp_status.strip(),
        (reason_non_use or "").strip(),
        user["username"],
        user["role"],
    ]

    try:
        append_row_to_worksheet(CORE_WORKSHEET, headers=CORE_HEADERS, row=row)
        st.toast("Saved successfully.")
        st.balloons()
        read_all_records.clear()
    except Exception as e:
        st.error(f"Failed to save to Google Sheets: {e}")


def tab_builder_view() -> None:
    st.subheader("TAB 2 — Dynamic Tab Builder (Admin)")
    st.caption("Create new data-entry forms. Each new form writes to a separate worksheet.")

    with st.form("tab_builder", clear_on_submit=False):
        tab_name = st.text_input("Tab Name", placeholder="Example: Referrals")
        st.markdown("#### Fields")

        fields = st.session_state.get("tab_builder_fields", [])
        if not fields:
            fields = [{"name": "", "type": "Text", "options": ""}]
            st.session_state["tab_builder_fields"] = fields

        for i, f in enumerate(fields):
            cc1, cc2, cc3, cc4 = st.columns([1.2, 0.9, 1.6, 0.6])
            with cc1:
                f["name"] = st.text_input(f"Field Name #{i+1}", value=f.get("name", ""), key=f"tb_name_{i}")
            with cc2:
                f["type"] = st.selectbox(
                    f"Type #{i+1}",
                    ["Text", "Number", "Dropdown"],
                    index=["Text", "Number", "Dropdown"].index(f.get("type", "Text")),
                    key=f"tb_type_{i}",
                )
            with cc3:
                if f["type"] == "Dropdown":
                    f["options"] = st.text_input(
                        f"Dropdown options #{i+1} (comma-separated)",
                        value=f.get("options", ""),
                        key=f"tb_opt_{i}",
                    )
                else:
                    f["options"] = ""
                    st.text_input(
                        f"Dropdown options #{i+1} (comma-separated)",
                        value="(not used)",
                        disabled=True,
                        key=f"tb_opt_disabled_{i}",
                    )
            with cc4:
                f["_remove"] = st.checkbox("Remove", key=f"tb_rm_{i}")

        add_field = st.form_submit_button("+ Add Field")
        save = st.form_submit_button("Save Tab")

    if add_field:
        st.session_state["tab_builder_fields"].append({"name": "", "type": "Text", "options": ""})
        st.rerun()

    if save:
        cleaned: list[DynamicField] = []
        for f in st.session_state["tab_builder_fields"]:
            if f.get("_remove"):
                continue
            name = str(f.get("name", "")).strip()
            ftype = str(f.get("type", "Text")).strip()
            if not name:
                continue
            options: list[str] = []
            if ftype == "Dropdown":
                options = [x.strip() for x in str(f.get("options", "")).split(",") if x.strip()]
            cleaned.append(DynamicField(name=name, type=ftype, options=options))

        if not tab_name.strip():
            st.error("Tab Name is required.")
            return
        if not cleaned:
            st.error("Add at least one field.")
            return

        try:
            save_tab_definition(tab_name=tab_name, fields=cleaned)
            st.success("Dynamic tab saved. It will appear in the sidebar.")
            read_all_records.clear()
            st.session_state["tab_builder_fields"] = [{"name": "", "type": "Text", "options": ""}]
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save dynamic tab definition: {e}")


def dynamic_tab_view(tab: DynamicTab, user: dict[str, str]) -> None:
    st.subheader(f"Dynamic Form — {tab.tab_name}")

    headers = ["created_at"] + [f.name for f in tab.fields] + ["submitted_by", "role"]

    with st.form(f"dyn_{tab.worksheet_title}", clear_on_submit=True):
        values: dict[str, Any] = {}
        for f in tab.fields:
            if f.type == "Text":
                values[f.name] = st.text_input(f.name)
            elif f.type == "Number":
                values[f.name] = st.number_input(f.name, step=1.0)
            else:
                opts = f.options or []
                values[f.name] = st.selectbox(f.name, opts if opts else [""])
        submitted = st.form_submit_button("Submit")

    if not submitted:
        return

    errs = []
    for f in tab.fields:
        v = values.get(f.name, "")
        if f.type == "Number":
            if v is None:
                errs.append(f"Field ({f.name}) is required.")
        else:
            if not str(v).strip():
                errs.append(f"Field ({f.name}) is required.")
    if errs:
        for e in errs:
            st.warning(e)
        return

    row = [dt.datetime.utcnow().isoformat()] + [values.get(f.name, "") for f in tab.fields] + [user["username"], user["role"]]
    try:
        append_row_to_worksheet(tab.worksheet_title, headers=headers, row=row)
        st.toast("Saved successfully.")
        read_all_records.clear()
    except Exception as e:
        st.error(f"Failed to save to Google Sheets: {e}")


def dashboard_view() -> None:
    try:
        records = read_all_records(CORE_WORKSHEET)
    except Exception as e:
        st.error(f"Could not read from Google Sheets worksheet `{CORE_WORKSHEET}`: {e}")
        return
    render_dashboard(records)


# ==========================
# APP ENTRY
# ==========================

def main() -> None:
    set_page()
    inject_css()
    _init_state()

    if not st.session_state.get("user"):
        login_view()
        return

    user = st.session_state["user"]
    role = user["role"]

    st.title(APP_TITLE)

    # Load dynamic tabs
    try:
        dynamic_tabs = load_dynamic_tabs()
    except Exception:
        dynamic_tabs = []

    nav = sidebar_nav(role=role, dynamic_tabs=dynamic_tabs)
    st.session_state["nav"] = nav

    if nav == "Core Form":
        core_form_view(user=user)
        return

    if nav == "Dashboard":
        if role != "Admin":
            st.error("Admins only.")
            return
        dashboard_view()
        return

    if nav == "+ Tab Builder":
        if role != "Admin":
            st.error("Admins only.")
            return
        tab_builder_view()
        return

    if nav.startswith("🧩 "):
        name = nav.replace("🧩 ", "", 1).strip()
        tab = next((t for t in dynamic_tabs if t.tab_name == name), None)
        if not tab:
            st.error("This dynamic tab no longer exists.")
            return
        dynamic_tab_view(tab=tab, user=user)
        return

    st.info("Select a page from the sidebar.")


if __name__ == "__main__":
    main()

