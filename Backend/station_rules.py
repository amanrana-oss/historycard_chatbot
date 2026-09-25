from __future__ import annotations

from pathlib import Path
import re
from typing import Dict, List, Any

import pandas as pd

import config

MASTER_FILE = Path(__file__).parent / "station_master.csv"


def _norm_text(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in {"na", "nan", "none", "null", ""}:
        return ""
    return s


def _dedupe_keep_order(items: List[str]) -> List[str]:
    out = []
    seen = set()
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


def normalize_station(station: str | None) -> str | None:
    if not station:
        return None
    s = str(station).strip().upper().replace(" ", "")
    m = re.fullmatch(r"ML[-]?(\d{1,2})", s)
    if m:
        return f"ML-{int(m.group(1)):02d}"
    return s


def _expand_numeric_spec(spec: str) -> List[int]:
    """
    Handles:
      1-16    → [1,2,...,16]
      1,2     → [1,2]
      1       → [1]
      1-5,10  → [1,2,3,4,5,10]
    """
    items: List[int] = []
    for chunk in re.split(r"\s*,\s*", spec.strip()):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", chunk)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            step = 1 if start <= end else -1
            items.extend(range(start, end + step, step))
        elif re.fullmatch(r"\d+", chunk):
            items.append(int(chunk))
    return items


def parse_barcode_spec(spec: str) -> List[str]:
    """
    '1,2'  → ['Barcode_1', 'Barcode_2']
    '1'    → ['Barcode_1']
    'NA'   → []
    """
    spec = _norm_text(spec)
    if not spec:
        return []
    numbers = _expand_numeric_spec(spec)
    return [f"Barcode_{n}" for n in numbers]


def parse_torque_spec(spec: str) -> List[str]:
    """
    Handles all variants found in master:
      N2-(1-4)          → N2_torque1, N2_torque2, N2_torque3, N2_torque4
      N5(1-16),N4(1-16) → N5_torque1..16, N4_torque1..16
      N2(1-2)           → N2_torque1, N2_torque2
      N2-1              → N2_torque1
      N2(1,2),N3(1)     → N2_torque1, N2_torque2, N3_torque1
      N4(1),N2(1)       → N4_torque1, N2_torque1
      N1(1-2),N2(1)     → N1_torque1, N1_torque2, N2_torque1
    """
    spec = _norm_text(spec)
    if not spec:
        return []

    # Normalise: remove all spaces
    s = spec.replace(" ", "").upper()
    cols: List[str] = []

    # Pattern 1: N2-(1-4) or N2(1-4) or N2(1,2)
    for m in re.finditer(r"([A-Z]\d)-?\(([^)]*)\)", s):
        prefix = m.group(1)   # e.g. N2
        body = m.group(2)     # e.g. 1-4  or  1,2
        for n in _expand_numeric_spec(body):
            cols.append(f"{prefix}_torque{n}")

    # Pattern 2: N2-1 (single torque, no parens) — only if pattern 1 found nothing for this prefix
    for m in re.finditer(r"([A-Z]\d)-(\d+)(?!\d)", s):
        prefix = m.group(1)
        n = int(m.group(2))
        candidate = f"{prefix}_torque{n}"
        cols.append(candidate)

    return _dedupe_keep_order(cols)


def parse_leak_spec(spec: str) -> List[str]:
    spec = _norm_text(spec)
    if not spec:
        return []
    if spec.lower() in {"yes", "y", "true", "1", "leak_value"}:
        return [
            "Leak_Value",
            "Leak1",
            "Leak2",
            "Leak3",
            "Leak1_Status",
            "Leak2_Status",
            "Leak3_Status",
            "Oil_Filling_Value",
        ]
    return []


def load_station_master() -> Dict[str, Dict[str, Any]]:
    if not MASTER_FILE.exists():
        return {}

    df = pd.read_csv(MASTER_FILE).fillna("")
    master: Dict[str, Dict[str, Any]] = {}

    for _, row in df.iterrows():
        station = normalize_station(row.get("Station", ""))
        if not station:
            continue

        barcode_spec = _norm_text(row.get("Barcode", ""))
        leak_spec = _norm_text(row.get("Leak", ""))
        torque_spec = _norm_text(row.get("Torque", ""))

        master[station] = {
            "station": station,
            "barcode_spec": barcode_spec,
            "leak_spec": leak_spec,
            "torque_spec": torque_spec,
            "barcode_columns": parse_barcode_spec(barcode_spec),
            "leak_columns": parse_leak_spec(leak_spec),
            "torque_columns": parse_torque_spec(torque_spec),
        }

    return master


STATION_MASTER = load_station_master()


def get_station_rule(station: str | None) -> Dict[str, Any]:
    station = normalize_station(station)
    if not station:
        return {}
    return STATION_MASTER.get(station, {})


def build_station_guide() -> str:
    if not STATION_MASTER:
        return "No station master loaded."

    def _key(x: str) -> int:
        m = re.fullmatch(r"ML-(\d{2})", x)
        return int(m.group(1)) if m else 999

    lines = []
    for station in sorted(STATION_MASTER.keys(), key=_key):
        rule = STATION_MASTER[station]
        bc = rule["barcode_spec"] or "NA"
        lk = rule["leak_spec"] or "NA"
        tq = rule["torque_spec"] or "NA"
        lines.append(f"{station}: barcode={bc}; leak={lk}; torque={tq}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Column resolvers — master-driven, schema-validated
# ─────────────────────────────────────────────

def get_barcode_columns(schema_columns: List[str], station: str | None = None) -> List[str]:
    """
    If station is given → return only what that station's master says.
    If station is None  → return Barcode columns for ALL stations that have barcodes.
    Always validate against real schema.
    """
    schema_set = set(schema_columns)

    if station:
        rule = get_station_rule(station)
        master_cols = rule.get("barcode_columns", [])
        validated = [c for c in master_cols if c in schema_set]
        # Fallback: generic schema scan
        if not validated:
            validated = [c for c in schema_columns if c.lower().startswith("barcode")]
        return validated

    # No station → union of ALL stations that have barcodes
    all_bc: List[str] = []
    for rule in STATION_MASTER.values():
        for c in rule.get("barcode_columns", []):
            if c in schema_set and c not in all_bc:
                all_bc.append(c)
    if not all_bc:
        all_bc = [c for c in schema_columns if c.lower().startswith("barcode")]
    return all_bc


def get_stations_with_barcode() -> List[str]:
    """Return list of stations that provide barcode data."""
    return [s for s, rule in STATION_MASTER.items() if rule.get("barcode_columns")]


def get_stations_with_torque() -> List[str]:
    """Return list of stations that provide torque data."""
    return [s for s, rule in STATION_MASTER.items() if rule.get("torque_columns")]


def get_stations_with_leak() -> List[str]:
    """Return list of stations that provide leak data (only ML-47)."""
    return [s for s, rule in STATION_MASTER.items() if rule.get("leak_columns")]


def get_leak_columns(schema_columns: List[str], station: str | None = None) -> List[str]:
    """Leak data lives only at ML-47."""
    preferred = [
        "Leak_Value",
        "Leak1",
        "Leak2",
        "Leak3",
        "Leak1_Status",
        "Leak2_Status",
        "Leak3_Status",
        "Oil_Filling_Value",
    ]
    schema_set = set(schema_columns)

    if station:
        rule = get_station_rule(station)
        master_cols = rule.get("leak_columns", [])
        validated = [c for c in master_cols if c in schema_set]
        return validated if validated else []

    # No station → return leak columns (only meaningful from ML-47)
    return [c for c in preferred if c in schema_set]


def get_torque_columns(schema_columns: List[str], station: str | None = None) -> List[str]:
    """
    Return torque columns exactly as defined in master for that station.
    If no station → all torque columns in schema (cross-station query).
    """
    schema_set = set(schema_columns)

    if station:
        rule = get_station_rule(station)
        master_cols = rule.get("torque_columns", [])
        validated = [c for c in master_cols if c in schema_set]
        if not validated:
            validated = [c for c in schema_columns if "torque" in c.lower()]
        return validated

    return [c for c in schema_columns if "torque" in c.lower()]


def get_status_columns(schema_columns: List[str]) -> List[str]:
    preferred = [
        "Stn_Status",
        "Printer_Status",
        "Child_Part_Status",
        "Torque_Status",
        "Rejected_Reason",
        "Rejected_Station",
        "ReworkCount",
    ]
    return [c for c in preferred if c in schema_columns]


def get_core_timeline_columns(schema_columns: List[str]) -> List[str]:
    preferred = [
        "Engine_Number",
        "Stn_Number",
        "Date_Time",
        "Stn_Status",
        "Barcode_1",
        "Barcode_2",
        "Barcode_3",
        "Torque_Status",
        "Leak1_Status",
        "Leak2_Status",
        "Leak3_Status",
        "Leak_Value",
        "Rejected_Reason",
        "Rejected_Station",
        "ReworkCount",
        "EmployeeName",
        "EmpID",
        "DeviceName",
        "DeviceID",
    ]
    return [c for c in preferred if c in schema_columns]


def has_parameter_for_station(station: str | None, parameter: str) -> bool:
    rule = get_station_rule(station)
    parameter = (parameter or "").lower()
    if parameter == "barcode":
        return bool(rule.get("barcode_columns"))
    if parameter == "leak":
        return bool(rule.get("leak_columns"))
    if parameter == "torque":
        return bool(rule.get("torque_columns"))
    return False