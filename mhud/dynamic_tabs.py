from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

from mhud.sheets import META_WORKSHEET, append_row_to_worksheet, read_all_records, safe_sheet_title


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
    payload = []
    for f in fields:
        payload.append(
            {
                "name": f.name,
                "type": f.type,
                "options": f.options or [],
            }
        )
    return json.dumps(payload, ensure_ascii=False)


def _schema_from_json(schema_json: str) -> list[DynamicField]:
    raw = json.loads(schema_json or "[]")
    out: list[DynamicField] = []
    if not isinstance(raw, list):
        return out
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
        if ftype == "Dropdown":
            if not isinstance(options, list):
                options = []
            options = [str(x).strip() for x in options if str(x).strip()]
        else:
            options = []
        out.append(DynamicField(name=name, type=ftype, options=options))
    return out


def save_tab_definition(tab_name: str, fields: list[DynamicField]) -> DynamicTab:
    tab_name = (tab_name or "").strip()
    worksheet_title = safe_sheet_title(f"tab_{tab_name}")
    schema_json = _schema_to_json(fields)
    append_row_to_worksheet(
        META_WORKSHEET,
        headers=META_HEADERS,
        row=[dt.datetime.utcnow().isoformat(), tab_name, worksheet_title, schema_json],
    )
    return DynamicTab(tab_name=tab_name, worksheet_title=worksheet_title, fields=fields)


def load_dynamic_tabs() -> list[DynamicTab]:
    try:
        rows = read_all_records(META_WORKSHEET)
    except Exception:
        return []

    latest: dict[str, dict] = {}
    for r in rows:
        tab_name = str(r.get("tab_name", "")).strip()
        if not tab_name:
            continue
        latest[tab_name] = r

    out: list[DynamicTab] = []
    for tab_name, r in latest.items():
        worksheet_title = str(r.get("worksheet_title", "")).strip() or safe_sheet_title(f"tab_{tab_name}")
        fields = _schema_from_json(str(r.get("schema_json", "") or "[]"))
        if fields:
            out.append(DynamicTab(tab_name=tab_name, worksheet_title=worksheet_title, fields=fields))
    out.sort(key=lambda t: t.tab_name.lower())
    return out

