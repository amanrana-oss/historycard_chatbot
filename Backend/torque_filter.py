"""
torque_filter.py
================
Station-aware torque column filtering.

Rules:
  - Only columns defined in STATION_TORQUE_CONFIG for the given station are used.
  - After fetching data, columns where ALL values are 0, null, or empty are dropped.
  - Never guesses or invents column names.
  - If a station has no torque config -> returns empty immediately.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Master torque column map  (single source of truth — never changes at runtime)
# ─────────────────────────────────────────────────────────────────────────────
STATION_TORQUE_CONFIG: Dict[str, List[str]] = {
    "ML-08": [f"N2_torque{i}" for i in range(1, 5)],
    "ML-10": [f"N5_torque{i}" for i in range(1, 17)] + [f"N4_torque{i}" for i in range(1, 17)],
    "ML-11": ["N2_torque1", "N2_torque2"],
    "ML-12": ["N2_torque1"],
    "ML-13": ["N2_torque1"],
    "ML-17": [f"N5_torque{i}" for i in range(1, 7)] + [f"N4_torque{i}" for i in range(1, 5)],
    "ML-20": [f"N5_torque{i}" for i in range(1, 5)] + ["N4_torque1", "N4_torque4"],
    "ML-22": ["N2_torque1", "N2_torque2", "N3_torque1", "N1_torque1"],
    "ML-25": [f"N5_torque{i}" for i in range(1, 4)] + ["N4_torque1", "N3_torque1"],
    "ML-27": [f"N5_torque{i}" for i in range(1, 6)] + ["N4_torque1", "N4_torque5"],
    "ML-28": ["N4_torque1", "N2_torque1"],
    "ML-31": ["N2_torque1"],
    "ML-33": ["N1_torque1", "N1_torque2", "N2_torque1"],
    "ML-38": ["N5_torque1", "N5_torque14", "N4_torque1", "N4_torque14"],
    "ML-39": ["N2_torque1", "N2_torque2", "N1_torque1"],
    "ML-43": ["N5_torque1", "N5_torque18", "N4_torque1", "N4_torque18"],
    "ML-44": ["N5_torque1", "N5_torque3", "N4_torque1", "N4_torque3"],
    "ML-45": ["N1_torque1", "N1_torque2", "N2_torque1"],
    "ML-48": ["N1_torque1"],
    "ML-49": ["N2_torque1"],
    "ML-50": ["N2_torque1", "N1_torque1", "N1_torque2"],
}

STATIONS_WITH_TORQUE: List[str] = sorted(
    STATION_TORQUE_CONFIG.keys(),
    key=lambda s: int(s.replace("ML-", ""))
)


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_torque_columns_for_station(
    station: Optional[str],
    schema_columns: List[str],
) -> List[str]:
    """
    Return torque column names that:
      1. Are defined in STATION_TORQUE_CONFIG for `station`.
      2. Actually exist in the DB schema (`schema_columns`).

    If station is None → returns all torque cols across all stations
    that exist in schema (cross-station query).
    Returns [] if station has no config or none of its cols are in schema.
    """
    schema_set = set(schema_columns)

    if station:
        station = station.upper().strip()
        cols = STATION_TORQUE_CONFIG.get(station, [])
        return [c for c in cols if c in schema_set]

    # Cross-station: union in station order, deduplicated
    seen: set = set()
    all_cols: List[str] = []
    for stn in STATIONS_WITH_TORQUE:
        for c in STATION_TORQUE_CONFIG[stn]:
            if c in schema_set and c not in seen:
                all_cols.append(c)
                seen.add(c)
    return all_cols


def _is_blank_series(series: "pd.Series") -> bool:
    """Return True if every value in series is null, 0, or empty string."""
    def _blank(v) -> bool:
        if v is None:
            return True
        if isinstance(v, float) and (v == 0.0 or pd.isna(v)):
            return True
        if isinstance(v, int) and v == 0:
            return True
        if isinstance(v, str) and v.strip() in {"", "0", "0.0", "0.000"}:
            return True
        return False
    return series.apply(_blank).all()


def filter_torque_dataframe(
    df: "pd.DataFrame",
    station: Optional[str],
    anchor_cols: List[str],
) -> Tuple["pd.DataFrame", List[str]]:
    """
    Post-process a raw DataFrame from the DB:
      1. Keep only anchor_cols + valid torque columns for the station.
      2. Drop any torque column where every value is null, empty, or 0.
      3. Return (filtered_df, final_column_list).

    This is the single reusable entry point for torque post-processing.
    """
    if df is None or df.empty:
        return df, []

    schema_cols = list(df.columns)
    torque_cols = get_torque_columns_for_station(station, schema_cols)

    valid_anchor = [c for c in anchor_cols if c in df.columns]
    valid_torque = [c for c in torque_cols if c in df.columns]

    if not valid_torque:
        return pd.DataFrame(), []

    # Drop torque cols that are entirely blank/zero
    active_torque = [c for c in valid_torque if not _is_blank_series(df[c])]

    final_cols = valid_anchor + active_torque
    filtered_df = df[final_cols].copy() if final_cols else pd.DataFrame()
    return filtered_df, final_cols


def group_torque_by_station(
    df: "pd.DataFrame",
    anchor_cols: List[str],
    schema_cols: List[str],
) -> Dict[str, "pd.DataFrame"]:
    """
    For cross-station torque queries (no specific station given):
    Split the DataFrame by Stn_Number and apply per-station torque filtering.

    Returns { "ML-10": filtered_df, "ML-17": filtered_df, ... }
    Only stations with at least one non-zero torque value are included.
    """
    if df is None or df.empty or "Stn_Number" not in df.columns:
        return {}

    result: Dict[str, "pd.DataFrame"] = {}

    for stn, group_df in df.groupby("Stn_Number"):
        stn_str = str(stn).strip().upper()
        if stn_str not in STATION_TORQUE_CONFIG:
            continue
        filtered, cols = filter_torque_dataframe(
            group_df.reset_index(drop=True), stn_str, anchor_cols
        )
        if filtered is not None and not filtered.empty:
            result[stn_str] = filtered

    return dict(sorted(result.items(), key=lambda kv: int(kv[0].replace("ML-", ""))))
