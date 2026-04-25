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

