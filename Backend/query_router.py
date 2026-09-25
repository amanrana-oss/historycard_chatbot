from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

import config
from station_rules import (
    get_barcode_columns,
    get_leak_columns,
    get_status_columns,
    get_core_timeline_columns,
    get_stations_with_barcode,
    get_stations_with_leak,
    normalize_station,
)
from torque_filter import (
    STATION_TORQUE_CONFIG,
    STATIONS_WITH_TORQUE,
    get_torque_columns_for_station,
)

TABLE = f"[{config.TABLE_SCHEMA}].[{config.TABLE_NAME}]"

# ─────────────────────────────────────────────
# Leak data is available at these stations.
# ─────────────────────────────────────────────
LEAK_STATIONS = ["ML-47", "ML-53"]
LEAK_COLUMNS = [
    "Leak_Value", "Leak1", "Leak2", "Leak3",
    "Leak1_Status", "Leak2_Status", "Leak3_Status",
    "Oil_Filling_Value",
]

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _station_sort_expr() -> str:
    return "TRY_CAST(REPLACE(Stn_Number, 'ML-', '') AS INT)"


def _engine_expr() -> str:
    return "UPPER(LTRIM(RTRIM(Engine_Number)))"


def _normalize_engine(value: str | None) -> str:
    return (value or "").strip().upper()


def _nonnull_expr(col: str) -> str:
    return (
        f"NULLIF(LTRIM(RTRIM(COALESCE(CONVERT(NVARCHAR(4000), [{col}]), ''))), '') IS NOT NULL"
    )


def _any_nonnull_predicate(cols: List[str]) -> str:
    if not cols:
        return "1=1"
    return "(" + " OR ".join(_nonnull_expr(c) for c in cols) + ")"


def _in_clause(values: List[str]) -> Tuple[str, List[str]]:
    placeholders = ",".join(["?"] * len(values))
    return f"({placeholders})", list(values)


def _append_common_filters(
    clauses: List[str],
    params: List[Any],
    plan: Dict[str, Any],
    skip_station: bool = False,
):
    engine_numbers = [e for e in (plan.get("engine_numbers") or []) if e]
    station = normalize_station(plan.get("station"))
    date_from = plan.get("date_from")
    date_to = plan.get("date_to")
    employee = plan.get("employee")

    if engine_numbers:
        if len(engine_numbers) == 1:
            clauses.append(f"{_engine_expr()} = ?")
            params.append(_normalize_engine(engine_numbers[0]))
        else:
            in_sql, in_params = _in_clause([_normalize_engine(e) for e in engine_numbers[:10]])
            clauses.append(f"{_engine_expr()} IN {in_sql}")
            params.extend(in_params)

    if station and not skip_station:
        clauses.append("Stn_Number = ?")
        params.append(station)

    if date_from:
        clauses.append("Date_Time >= ?")
        params.append(date_from)

    if date_to:
        clauses.append("Date_Time < ?")
        params.append(date_to)

    if employee:
        clauses.append("(EmployeeName = ? OR EmpID = ? OR EmployeeID = ?)")
        params.extend([employee, employee, employee])


def _safe_cols(cols: List[str], schema_columns: List[str]) -> List[str]:
    schema_set = set(schema_columns)
    out = []
    for c in cols:
        if c in schema_set and c not in out:
            out.append(c)
    return out


def _anchor_cols(schema_columns: List[str]) -> List[str]:
    return _safe_cols(["Engine_Number", "Stn_Number", "Date_Time"], schema_columns)


def _date_clause_from_days(days: int) -> str:
    return f"Date_Time >= DATEADD(DAY, -{days}, GETDATE())"


# ─────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────
def build_query(plan: Dict[str, Any], schema_columns: List[str]):
    """
    Returns (sql, params, meta, error).
    error is None on success.
    """
    intent = plan.get("intent", "unknown")

    engine_numbers = [e for e in (plan.get("engine_numbers") or []) if e]
    engine = engine_numbers[0] if engine_numbers else None
    engine2 = engine_numbers[1] if len(engine_numbers) > 1 else None
    station = normalize_station(plan.get("station"))
    parameter = (plan.get("parameter") or "").lower().strip()
    date_from = plan.get("date_from")
    date_to = plan.get("date_to")

    # ── greeting / casual chat ──────────────────────────────────────────────
    if intent in ("greeting", "casual_question"):
        return None, None, {"focus": "chat_only"}, None

    # ── engine_summary ──────────────────────────────────────────────────────
    if intent == "engine_summary":
        if not engine:
            return None, None, None, "engine_missing"
        sql = f"""
            SELECT
                Engine_Number,
                COUNT(*) AS total_stations,
                MIN(Date_Time) AS start_time,
                MAX(Date_Time) AS end_time,
                SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                         OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                         THEN 1 ELSE 0 END) AS failure_count,
                SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                         OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                         THEN 1 ELSE 0 END) AS rejection_count,
                SUM(COALESCE(TRY_CAST(ReworkCount AS INT), 0)) AS total_rework,
                SUM(CASE WHEN COALESCE(Torque_Status,'') <> 'OK' THEN 1 ELSE 0 END) AS torque_issues,
                SUM(CASE WHEN COALESCE(Leak1_Status,'') <> 'OK'
                          OR COALESCE(Leak2_Status,'') <> 'OK'
                          OR COALESCE(Leak3_Status,'') <> 'OK'
                         THEN 1 ELSE 0 END) AS leak_issues
            FROM {TABLE}
            WHERE {_engine_expr()} = ?
            GROUP BY Engine_Number
        """
        return sql, [_normalize_engine(engine)], {"focus": "engine_summary"}, None

    # ── engine_timeline ─────────────────────────────────────────────────────
    if intent == "engine_timeline":
        if not engine:
            return None, None, None, "engine_missing"
        selected = _safe_cols(get_core_timeline_columns(schema_columns), schema_columns)
        for m in ["Engine_Number", "Stn_Number", "Date_Time"]:
            if m not in selected:
                selected.insert(0, m)
        sql = f"""
            SELECT {", ".join(selected)}
            FROM {TABLE}
            WHERE {_engine_expr()} = ?
            ORDER BY {_station_sort_expr()}, Date_Time
        """
        return sql, [_normalize_engine(engine)], {"focus": "engine_timeline", "selected_columns": selected}, None

    # ── station_detail / raw_station_row ────────────────────────────────────
    if intent in ("station_detail", "raw_station_row"):
        if not engine or not station:
            return None, None, None, "Need engine number and station number."
        sql = f"""
            SELECT TOP 1 *
            FROM {TABLE}
            WHERE {_engine_expr()} = ? AND Stn_Number = ?
            ORDER BY Date_Time DESC
        """
        return sql, [_normalize_engine(engine), station], {"focus": intent}, None

    # ── latest_status ────────────────────────────────────────────────────────
    if intent == "latest_status":
        if not engine:
            return None, None, None, "engine_missing"
        selected = _safe_cols([
            "Engine_Number", "Stn_Number", "Date_Time", "Stn_Status",
            "Torque_Status", "Leak1_Status", "Leak2_Status", "Leak3_Status",
            "Rejected_Reason", "Rejected_Station", "ReworkCount",
            "EmployeeName", "DeviceName",
        ], schema_columns)
        sql = f"""
            SELECT TOP 1 {", ".join(selected)}
            FROM {TABLE}
            WHERE {_engine_expr()} = ?
            ORDER BY Date_Time DESC
        """
        return sql, [_normalize_engine(engine)], {"focus": "latest_status", "selected_columns": selected}, None

    # ── first_failure ────────────────────────────────────────────────────────
    if intent == "first_failure":
        if not engine:
            return None, None, None, "engine_missing"
        sql = f"""
            SELECT TOP 1
                Stn_Number, Date_Time, Stn_Status, Torque_Status,
                Leak1_Status, Leak2_Status, Leak3_Status, Leak_Value,
                Rejected_Reason, Rejected_Station, ReworkCount
            FROM {TABLE}
            WHERE {_engine_expr()} = ?
              AND (
                    COALESCE(Stn_Status,'') <> 'OK'
                 OR UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                 OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                 OR ISNULL(ReworkCount, 0) > 0
                 OR COALESCE(Torque_Status,'') <> 'OK'
                 OR COALESCE(Leak1_Status,'') <> 'OK'
                 OR COALESCE(Leak2_Status,'') <> 'OK'
                 OR COALESCE(Leak3_Status,'') <> 'OK'
              )
            ORDER BY {_station_sort_expr()}, Date_Time
        """
        return sql, [_normalize_engine(engine)], {"focus": "first_failure"}, None

    # ── failure_summary ──────────────────────────────────────────────────────
    if intent == "failure_summary":
        if not engine:
            return None, None, None, "engine_missing"
        sql = f"""
            SELECT
                Stn_Number, Date_Time, Stn_Status, Torque_Status,
                Leak1_Status, Leak2_Status, Leak3_Status, Leak_Value,
                Rejected_Station, Rejected_Reason, ReworkCount
            FROM {TABLE}
            WHERE {_engine_expr()} = ?
              AND (
                    COALESCE(Stn_Status,'') <> 'OK'
                 OR UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                 OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                 OR ISNULL(ReworkCount, 0) > 0
                 OR COALESCE(Torque_Status,'') <> 'OK'
                 OR COALESCE(Leak1_Status,'') <> 'OK'
                 OR COALESCE(Leak2_Status,'') <> 'OK'
                 OR COALESCE(Leak3_Status,'') <> 'OK'
              )
            ORDER BY {_station_sort_expr()}, Date_Time
        """
        return sql, [_normalize_engine(engine)], {"focus": "failure_summary"}, None

    # ── rework_summary ───────────────────────────────────────────────────────
    if intent == "rework_summary":
        if not engine:
            return None, None, None, "engine_missing"
        sql = f"""
            SELECT Stn_Number, Date_Time, ReworkCount, Rejected_Reason, Rejected_Station
            FROM {TABLE}
            WHERE {_engine_expr()} = ?
              AND ISNULL(ReworkCount, 0) > 0
            ORDER BY {_station_sort_expr()}, Date_Time
        """
        return sql, [_normalize_engine(engine)], {"focus": "rework_summary"}, None

    # ── rejection_summary ────────────────────────────────────────────────────
    if intent == "rejection_summary":
        if not engine:
            return None, None, None, "engine_missing"
        sql = f"""
            SELECT Stn_Number, Date_Time, Rejected_Station, Rejected_Reason, Stn_Status
            FROM {TABLE}
            WHERE {_engine_expr()} = ?
              AND (
                    UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                 OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
              )
            ORDER BY {_station_sort_expr()}, Date_Time
        """
        return sql, [_normalize_engine(engine)], {"focus": "rejection_summary"}, None

    # ── compare_engines ──────────────────────────────────────────────────────
    if intent == "compare_engines":
        if not engine or not engine2:
            return None, None, None, "Need two engine numbers to compare."
        sql = f"""
            SELECT
                Engine_Number,
                COUNT(*) AS total_stations,
                MIN(Date_Time) AS start_time,
                MAX(Date_Time) AS end_time,
                SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                         OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                         THEN 1 ELSE 0 END) AS failure_count,
                SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                         OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                         THEN 1 ELSE 0 END) AS rejection_count,
                SUM(ISNULL(ReworkCount, 0)) AS total_rework
            FROM {TABLE}
            WHERE {_engine_expr()} IN (?, ?)
            GROUP BY Engine_Number
            ORDER BY Engine_Number
        """
        return sql, [_normalize_engine(engine), _normalize_engine(engine2)], {"focus": "compare_engines"}, None

    # ── date_range_history ───────────────────────────────────────────────────
    if intent == "date_range_history":
        if not engine or not date_from or not date_to:
            return None, None, None, "engine_missing"
        selected = _safe_cols([
            "Engine_Number", "Stn_Number", "Date_Time", "Stn_Status",
            "Torque_Status", "Leak1_Status", "Leak2_Status", "Leak3_Status",
            "Leak_Value", "Rejected_Reason", "ReworkCount",
        ], schema_columns)
        sql = f"""
            SELECT {", ".join(selected)}
            FROM {TABLE}
            WHERE {_engine_expr()} = ? AND Date_Time >= ? AND Date_Time < ?
            ORDER BY Date_Time
        """
        return sql, [_normalize_engine(engine), date_from, date_to], {"focus": "date_range_history"}, None

    # ── employee_activity ────────────────────────────────────────────────────
    if intent == "employee_activity":
        employee = plan.get("employee")
        if not employee:
            return None, None, None, "Need employee name or ID."
        selected = _safe_cols([
            "Engine_Number", "Stn_Number", "Date_Time", "Stn_Status",
            "EmployeeName", "EmpID", "EmployeeID", "DeviceName", "DeviceID",
        ], schema_columns)
        sql = f"""
            SELECT {", ".join(selected)}
            FROM {TABLE}
            WHERE EmployeeName = ? OR EmpID = ? OR EmployeeID = ?
            ORDER BY Date_Time DESC
        """
        return sql, [employee, employee, employee], {"focus": "employee_activity"}, None

    # ── checkpoint_detail ────────────────────────────────────────────────────
    if intent == "checkpoint_detail":
        if not engine:
            return None, None, None, "engine_missing"
        checkpoint_cols = [c for c in schema_columns if c.lower().startswith("checkpoints_")]
        if not checkpoint_cols:
            return None, None, None, "No checkpoint columns found in schema."
        selected = ["Engine_Number", "Stn_Number", "Date_Time"] + checkpoint_cols
        sql = f"""
            SELECT {", ".join(selected)}
            FROM {TABLE}
            WHERE {_engine_expr()} = ?
            ORDER BY {_station_sort_expr()}, Date_Time
        """
        return sql, [_normalize_engine(engine)], {"focus": "checkpoint_detail"}, None

    # ── station_parameter_query ──────────────────────────────────────────────
    if intent == "station_parameter_query":
        if not engine and not station and not date_from and not date_to:
            return None, None, None, "Please specify an engine number, station, or date."

        # ── LEAK: hardcoded ML-47 always ────────────────────────────────────
        if parameter == "leak":
            if station and station not in LEAK_STATIONS:
                return None, None, None, (
                    f"Leak values only exist at stations {', '.join(LEAK_STATIONS)}. "
                    f"Station {station} does not have leak data."
                )

            leak_cols = _safe_cols(LEAK_COLUMNS, schema_columns)
            if not leak_cols:
                return None, None, None, "No leak columns found in schema."

            anchor = _anchor_cols(schema_columns)
            selected = anchor + [c for c in leak_cols if c not in anchor]

            leak_station_sql, leak_station_params = _in_clause(
                [station] if station else LEAK_STATIONS
            )
            clauses: List[str] = [f"Stn_Number IN {leak_station_sql}"]
            params: List[Any] = leak_station_params

            if engine:
                clauses.append(f"{_engine_expr()} = ?")
                params.append(_normalize_engine(engine))
            if date_from:
                clauses.append("CAST(Date_Time AS DATETIME) >= CAST(? AS DATETIME)")
                params.append(date_from)
            if date_to:

                clauses.append("CAST(Date_Time AS DATETIME) < CAST(? AS DATETIME)")
                params.append(date_to)

            clauses.append(_any_nonnull_predicate(leak_cols))

            sql = f"""
                SELECT {", ".join(selected)}
                FROM {TABLE}
                WHERE {" AND ".join(clauses)}
                ORDER BY Date_Time DESC
            """
            return sql, params, {
                "focus": "station_parameter_query",
                "parameter": "leak",
                "station": station,
                "stations": LEAK_STATIONS,
                "note": "Leak data is available at ML-47 and ML-53",
                "selected_columns": selected,
            }, None

        # ── BARCODE ──────────────────────────────────────────────────────────
        elif parameter == "barcode":
            param_cols = get_barcode_columns(schema_columns, station=station)
            stations_with_data = get_stations_with_barcode()

            param_cols = _safe_cols(param_cols, schema_columns)
            if not param_cols:
                if station:
                    return None, None, None, (
                        f"Station {station} does not have barcode data. "
                        f"Stations with barcode data: {', '.join(sorted(stations_with_data)[:10])}"
                    )
                return None, None, None, "No barcode columns found in schema."

            anchor = _anchor_cols(schema_columns)
            selected = anchor + [c for c in param_cols if c not in anchor]

            clauses, params = [], []
            _append_common_filters(clauses, params, plan, skip_station=True)

            if station:
                clauses.append("Stn_Number = ?")
                params.append(station)
            elif stations_with_data:
                in_sql, in_params = _in_clause(stations_with_data)
                clauses.append(f"Stn_Number IN {in_sql}")
                params.extend(in_params)

            clauses.append(_any_nonnull_predicate(param_cols))
            where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

            sql = f"""
                SELECT {", ".join(selected)}
                FROM {TABLE} {where_sql}
                ORDER BY Date_Time DESC, {_station_sort_expr()}
            """
            return sql, params, {
                "focus": "station_parameter_query",
                "parameter": "barcode",
                "station": station,
                "selected_columns": selected,
            }, None

        # ── TORQUE ───────────────────────────────────────────────────────────
        elif parameter == "torque":
            # STATION_TORQUE_CONFIG is the single source of truth — no guessing
            param_cols = get_torque_columns_for_station(station, schema_columns)

            if not param_cols:
                if station:
                    return None, None, None, (
                        f"Station {station} does not have torque data. "
                        f"Stations with torque: {', '.join(STATIONS_WITH_TORQUE[:10])}"
                    )
                return None, None, None, "No torque columns found in schema."

            anchor = _anchor_cols(schema_columns)
            # Select all candidate cols; zero/null filtering done in main.py post-processing
            selected = anchor + [c for c in param_cols if c not in anchor]

            clauses, params = [], []
            _append_common_filters(clauses, params, plan, skip_station=True)

            if station:
                clauses.append("Stn_Number = ?")
                params.append(station)
            else:
                # Cross-station: restrict to only stations that have torque config
                in_sql, in_params = _in_clause(STATIONS_WITH_TORQUE)
                clauses.append(f"Stn_Number IN {in_sql}")
                params.extend(in_params)

            # Row-level filter: at least one torque col must be non-null/non-zero
            clauses.append(_any_nonnull_predicate(param_cols))
            where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

            sql = f"""
                SELECT {", ".join(selected)}
                FROM {TABLE} {where_sql}
                ORDER BY {_station_sort_expr()}, Date_Time DESC
            """
            return sql, params, {
                "focus": "station_parameter_query",
                "parameter": "torque",
                "station": station,
                "selected_columns": selected,
                "torque_filter": True,   # signal main.py to run post-processing
            }, None

        # ── STATUS ───────────────────────────────────────────────────────────
        elif parameter == "status":
            param_cols = _safe_cols([
                "Stn_Status", "Printer_Status", "Child_Part_Status",
                "Torque_Status", "Rejected_Reason", "Rejected_Station", "ReworkCount",
            ], schema_columns)

            anchor = _anchor_cols(schema_columns)
            selected = anchor + [c for c in param_cols if c not in anchor]

            clauses, params = [], []
            _append_common_filters(clauses, params, plan, skip_station=True)
            if station:
                clauses.append("Stn_Number = ?")
                params.append(station)

            where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT {", ".join(selected)}
                FROM {TABLE} {where_sql}
                ORDER BY Date_Time DESC, {_station_sort_expr()}
            """
            return sql, params, {
                "focus": "station_parameter_query",
                "parameter": "status",
                "station": station,
                "selected_columns": selected,
            }, None

        else:
            return None, None, None, "Please specify barcode, torque, leak, or status."

    # ── NEW: station_failures ────────────────────────────────────────────────
    if intent == "station_failures":
        days = 7
        date_clause = f"WHERE {_date_clause_from_days(days)}"
        if date_from:
            date_clause = "WHERE Date_Time >= ? AND Date_Time < ?"
        sql = f"""
            SELECT
                Stn_Number,
                COUNT(*) AS total_records,
                SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                         OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                         THEN 1 ELSE 0 END) AS failure_count,
                CAST(
                    100.0 * SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                                     OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                                     THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0)
                AS DECIMAL(5,2)) AS failure_rate_pct
            FROM {TABLE}
            {date_clause}
            GROUP BY Stn_Number
            HAVING SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                            OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                            THEN 1 ELSE 0 END) > 0
            ORDER BY failure_count DESC
        """
        params = [date_from, date_to] if date_from else []
        return sql, params, {"focus": "station_failures"}, None

    # ── NEW: rejection_reasons ───────────────────────────────────────────────
    if intent == "rejection_reasons":
        days = 7
        date_clause = f"AND {_date_clause_from_days(days)}"
        if date_from:
            date_clause = "AND Date_Time >= ? AND Date_Time < ?"
        sql = f"""
            SELECT TOP 15
                COALESCE(NULLIF(LTRIM(RTRIM(Rejected_Reason)),''), 'Unknown') AS reason,
                COUNT(*) AS count,
                COUNT(DISTINCT Engine_Number) AS engines_affected,
                COUNT(DISTINCT Stn_Number) AS stations_affected
            FROM {TABLE}
            WHERE NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
              {date_clause}
            GROUP BY COALESCE(NULLIF(LTRIM(RTRIM(Rejected_Reason)),''), 'Unknown')
            ORDER BY count DESC
        """
        params = [date_from, date_to] if date_from else []
        return sql, params, {"focus": "rejection_reasons"}, None

    # ── NEW: rework_stations ─────────────────────────────────────────────────
    if intent == "rework_stations":
        days = 7
        date_clause = f"AND {_date_clause_from_days(days)}"
        if date_from:
            date_clause = "AND Date_Time >= ? AND Date_Time < ?"
        sql = f"""
            SELECT TOP 15
                Stn_Number,
                SUM(ISNULL(TRY_CAST(ReworkCount AS INT), 0)) AS total_rework,
                COUNT(DISTINCT Engine_Number) AS engines_reworked,
                CAST(AVG(CAST(ISNULL(TRY_CAST(ReworkCount AS INT),0) AS FLOAT)) AS DECIMAL(5,2)) AS avg_rework_per_engine
            FROM {TABLE}
            WHERE ISNULL(TRY_CAST(ReworkCount AS INT), 0) > 0
              {date_clause}
            GROUP BY Stn_Number
            ORDER BY total_rework DESC
        """
        params = [date_from, date_to] if date_from else []
        return sql, params, {"focus": "rework_stations"}, None

    # ── NEW: failure_trend ───────────────────────────────────────────────────
    if intent == "failure_trend":
        days = 7
        date_label = plan.get("date_label", "")
        if date_label and "last_" in date_label and "_days" in date_label:
            try:
                days = int(date_label.replace("last_", "").replace("_days", ""))
            except ValueError:
                days = 7

        sql = f"""
            SELECT
                CAST(Date_Time AS DATE) AS date,
                COUNT(*) AS total_records,
                SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                         OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                         THEN 1 ELSE 0 END) AS failures,
                SUM(ISNULL(TRY_CAST(ReworkCount AS INT), 0)) AS reworks,
                COUNT(DISTINCT Engine_Number) AS engines_processed
            FROM {TABLE}
            WHERE Date_Time >= DATEADD(DAY, -{days}, GETDATE())
            GROUP BY CAST(Date_Time AS DATE)
            ORDER BY date ASC
        """
        return sql, [], {"focus": "failure_trend", "days": days}, None

    return None, None, None, "I could not understand that question. Please try rephrasing."