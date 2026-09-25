from __future__ import annotations

import asyncio
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from db import get_table_columns, run_query
from gemini_agent import answer_chat_message
from parser import parse_question
from query_router import build_query
from station_rules import STATION_MASTER, build_station_guide
from torque_filter import filter_torque_dataframe, group_torque_by_station

# ─────────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────────
app = FastAPI(title="Engine History API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=20)

# ─────────────────────────────────────────────
# In-memory cache
# ─────────────────────────────────────────────
_cache: Dict[str, Dict] = {}
CACHE_TTL_SECONDS = 60
SCHEMA_TTL_SECONDS = 300

TABLE = f"[{config.TABLE_SCHEMA}].[{config.TABLE_NAME}]"


def _cache_get(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    if entry and time.time() < entry["expires"]:
        return entry["value"]
    return None


def _cache_set(key: str, value: Any, ttl: int = CACHE_TTL_SECONDS):
    _cache[key] = {"value": value, "expires": time.time() + ttl}


def _make_cache_key(*args) -> str:
    return hashlib.md5(json.dumps(args, default=str, sort_keys=True).encode()).hexdigest()


# ─────────────────────────────────────────────
# Schema + Station Guide
# ─────────────────────────────────────────────
_schema_columns: List[str] = []
_station_guide: str = ""


async def _get_schema() -> List[str]:
    global _schema_columns
    cached = _cache_get("schema_columns")
    if cached:
        return cached
    cols = await asyncio.get_event_loop().run_in_executor(executor, get_table_columns)
    _schema_columns = cols
    _cache_set("schema_columns", cols, SCHEMA_TTL_SECONDS)
    return cols


@app.on_event("startup")
async def startup():
    global _schema_columns, _station_guide
    _schema_columns = await _get_schema()
    _station_guide = build_station_guide()


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
class ChatRequest(BaseModel):
    question: str
    station_filter: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class AnalyticsRequest(BaseModel):
    query_type: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    days: Optional[int] = 7


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _df_to_records(df: pd.DataFrame) -> List[Dict]:
    if df is None or df.empty:
        return []

    #  THIS IS THE FIX
    df = df.replace({float("nan"): None})   # handle NaN
    df = df.where(pd.notnull(df), None)     # handle pandas nulls

    return df.to_dict(orient="records")


def _normalize_engine(engine_number: str) -> str:
    return (engine_number or "").strip().upper()


def _engine_exists(engine_number: str) -> bool:
    sql = f"""
        SELECT TOP 1 1
        FROM {TABLE}
        WHERE UPPER(LTRIM(RTRIM(Engine_Number))) = ?
    """
    df = run_query(sql, (_normalize_engine(engine_number),))
    return not df.empty


def _validate_engine_in_result(df: pd.DataFrame, engine_number: str) -> Optional[str]:
    if df is None or df.empty:
        return (
            f"The engine number '{engine_number}' was not found in the database. "
            "Please verify the engine number and try again."
        )
    return None


def _make_friendly_error(err: str, plan: dict) -> str:
    engines = plan.get("engine_numbers") or []

    if err == "engine_missing":
        if engines:
            return (
                f"The engine number '{engines[0]}' was not found in the database. "
                "Please double-check the engine number and try again."
            )
        return "Please provide a valid engine number to run this query."

    err_lower = err.lower()
    if "does not have" in err_lower and "data" in err_lower:
        return err
    if "only exist" in err_lower or "only available" in err_lower:
        return err
    if "two engine" in err_lower:
        return "Please provide two engine numbers to compare, e.g. 'compare engine A and engine B'."
    if "date" in err_lower:
        return "A date is required for this query. Try adding 'today', 'this week', or a specific date."
    if "could not understand" in err_lower:
        return "I could not understand that question. Please try rephrasing or use one of the example questions."
    return err


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/stations")
async def get_stations():
    stations = sorted(STATION_MASTER.keys(), key=lambda x: int(x.replace("ML-", "")))
    return {"stations": stations}


@app.get("/schema")
async def get_schema():
    cols = await _get_schema()
    return {"columns": cols, "count": len(cols)}


@app.post("/chat")
async def chat(req: ChatRequest):

    schema_columns = await _get_schema()

    question = req.question.strip()

    if req.station_filter and req.station_filter != "(all)":
        if req.station_filter.upper() not in question.upper():
            question = f"{question} for {req.station_filter}"

    if req.date_from and req.date_to:
        q_lower = question.lower()
        has_date_hint = (" on " in q_lower) or (" from " in q_lower) or (" to " in q_lower)
        if not has_date_hint:
            if req.date_from == req.date_to:
                question = f"{question} on {req.date_from}"
            else:
                question = f"{question} from {req.date_from} to {req.date_to}"

    cache_key = _make_cache_key("chat", question)
    cached = _cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    plan = parse_question(question, schema_columns)

    if plan.get("intent") in {"greeting", "casual_question"}:
        reply = answer_chat_message(question)
        result = {
            "status": "success",
            "message": reply,
            "plan": plan,
            "data": [],
            "columns": [],
            "row_count": 0,
            "cached": False,
        }
        _cache_set(cache_key, result, ttl=15)
        return result

    if plan.get("needs_clarification"):
        return {
            "status": "clarification",
            "message": plan.get("clarification_question", "Please clarify your question."),
            "plan": plan,
            "data": [],
            "columns": [],
            "row_count": 0,
            "cached": False,
        }

    sql, params, meta, err = build_query(plan, schema_columns)
    print("\n====== DEBUG ======")
    print("QUESTION:", question)
    print("PLAN:", plan)
    print("FINAL SQL:", sql)
    print("PARAMS:", params)
    print("===================\n")
    if err:
        friendly = _make_friendly_error(err, plan)
        return {
            "status": "error",
            "message": friendly,
            "plan": plan,
            "data": [],
            "columns": [],
            "row_count": 0,
            "cached": False,
        }

    if sql is None:
        reply = answer_chat_message(question)
        result = {
            "status": "success",
            "message": reply,
            "plan": plan,
            "data": [],
            "columns": [],
            "row_count": 0,
            "cached": False,
        }
        _cache_set(cache_key, result, ttl=15)
        return result

    try:
        df = await asyncio.get_event_loop().run_in_executor(
            executor, lambda: run_query(sql, tuple(params))
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Database error: {str(e)}. Please try again.",
            "plan": plan,
            "data": [],
            "columns": [],
            "row_count": 0,
            "cached": False,
        }

    engine_numbers = plan.get("engine_numbers") or []
    if engine_numbers and (df is None or df.empty):
        if _engine_exists(engine_numbers[0]):
            return {
                "status": "empty",
                "message": "The engine exists, but no rows matched the selected filters. Try removing date/station filters.",
                "plan": plan,
                "data": [],
                "columns": [],
                "row_count": 0,
                "cached": False,
            }

        err_msg = _validate_engine_in_result(df, engine_numbers[0])
        return {
            "status": "not_found",
            "message": err_msg,
            "plan": plan,
            "data": [],
            "columns": [],
            "row_count": 0,
            "cached": False,
        }

    if df is None or df.empty:
        return {
            "status": "empty",
            "message": "No data found for your query. Try adjusting the filters or date range.",
            "plan": plan,
            "data": [],
            "columns": [],
            "row_count": 0,
            "cached": False,
        }

    # ── Torque post-processing: drop zero/null cols, group by station ──────
    is_torque = bool((meta or {}).get("torque_filter")) or (plan.get("parameter") == "torque")

    if is_torque:
        anchor = ["Engine_Number", "Stn_Number", "Date_Time"]
        target_station = plan.get("station")

        if target_station:
            # Single-station: keep only active (non-zero) torque cols
            df, final_cols = filter_torque_dataframe(df, target_station, anchor)
            if df is None or df.empty:
                return {
                    "status": "empty",
                    "message": (
                        f"No meaningful torque data for {target_station}. "
                        "All torque values are zero or null."
                    ),
                    "plan": plan,
                    "data": [],
                    "columns": [],
                    "row_count": 0,
                    "cached": False,
                }
            records = _df_to_records(df)
            columns = final_cols
        else:
            # Cross-station: group by Stn_Number, filter per station
            grouped = group_torque_by_station(df, anchor, list(df.columns))
            if not grouped:
                return {
                    "status": "empty",
                    "message": "No meaningful torque data found. All values are zero or null.",
                    "plan": plan,
                    "data": [],
                    "columns": [],
                    "row_count": 0,
                    "cached": False,
                }
            # Flatten with _station_group marker so UI can render sections
            all_records, all_cols_seen = [], []
            for stn, stn_df in grouped.items():
                for r in _df_to_records(stn_df):
                    r["_station_group"] = stn
                    all_records.append(r)
                for c in stn_df.columns:
                    if c not in all_cols_seen:
                        all_cols_seen.append(c)
            columns = ["_station_group"] + [c for c in all_cols_seen if c != "_station_group"]
            records = all_records
    else:
        records = _df_to_records(df)
        columns = list(df.dropna(axis=1, how="all").columns)

    result = {
        "status": "success",
        "message": None,
        "plan": plan,
        "meta": meta,
        "data": records,
        "columns": columns,
        "row_count": len(records),
        "sql_debug": sql if len(records) == 0 else None,
        "cached": False,
    }
    _cache_set(cache_key, result)
    return result


@app.post("/analytics/station-failures")
async def station_failures(req: AnalyticsRequest):
    cache_key = _make_cache_key("station_failures", req.date_from, req.date_to, req.days)
    cached = _cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    table = f"[{config.TABLE_SCHEMA}].[{config.TABLE_NAME}]"
    date_clause, params = _build_date_clause(req)

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
        FROM {table}
        {date_clause}
        GROUP BY Stn_Number
        HAVING SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                        OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                        THEN 1 ELSE 0 END) > 0
        ORDER BY failure_count DESC
    """

    df = await asyncio.get_event_loop().run_in_executor(
        executor, lambda: run_query(sql, tuple(params))
    )
    result = {"data": _df_to_records(df), "row_count": len(df), "cached": False}
    _cache_set(cache_key, result)
    return result


@app.post("/analytics/rejection-reasons")
async def rejection_reasons(req: AnalyticsRequest):
    cache_key = _make_cache_key("rejection_reasons", req.date_from, req.date_to, req.days)
    cached = _cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    table = f"[{config.TABLE_SCHEMA}].[{config.TABLE_NAME}]"
    date_clause, params = _build_date_clause(req)

    sql = f"""
        SELECT TOP 20
            COALESCE(NULLIF(LTRIM(RTRIM(Rejected_Reason)), ''), 'Unknown') AS reason,
            COUNT(*) AS count,
            COUNT(DISTINCT Engine_Number) AS engines_affected,
            COUNT(DISTINCT Stn_Number) AS stations_affected
        FROM {table}
        {date_clause}{"AND" if date_clause else "WHERE"}
            NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason, ''))), '') IS NOT NULL
        GROUP BY COALESCE(NULLIF(LTRIM(RTRIM(Rejected_Reason)), ''), 'Unknown')
        ORDER BY count DESC
    """
    if not date_clause:
        sql = sql.replace("AND\n            NULLIF", "WHERE\n            NULLIF")

    df = await asyncio.get_event_loop().run_in_executor(
        executor, lambda: run_query(sql, tuple(params))
    )
    result = {"data": _df_to_records(df), "row_count": len(df), "cached": False}
    _cache_set(cache_key, result)
    return result


@app.post("/analytics/rework-stations")
async def rework_stations(req: AnalyticsRequest):
    cache_key = _make_cache_key("rework_stations", req.date_from, req.date_to, req.days)
    cached = _cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    table = f"[{config.TABLE_SCHEMA}].[{config.TABLE_NAME}]"
    date_clause, params = _build_date_clause(req)
    and_or_where = "AND" if date_clause else "WHERE"

    sql = f"""
        SELECT TOP 20
            Stn_Number,
            SUM(ISNULL(TRY_CAST(ReworkCount AS INT), 0)) AS total_rework,
            COUNT(DISTINCT Engine_Number) AS engines_reworked,
            AVG(CAST(ISNULL(TRY_CAST(ReworkCount AS INT), 0) AS FLOAT)) AS avg_rework_per_engine
        FROM {table}
        {date_clause}
        {and_or_where} ISNULL(TRY_CAST(ReworkCount AS INT), 0) > 0
        GROUP BY Stn_Number
        ORDER BY total_rework DESC
    """

    df = await asyncio.get_event_loop().run_in_executor(
        executor, lambda: run_query(sql, tuple(params))
    )
    result = {"data": _df_to_records(df), "row_count": len(df), "cached": False}
    _cache_set(cache_key, result)
    return result


@app.post("/analytics/failure-trend")
async def failure_trend(req: AnalyticsRequest):
    days = req.days or 7
    cache_key = _make_cache_key("failure_trend", days)
    cached = _cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    table = f"[{config.TABLE_SCHEMA}].[{config.TABLE_NAME}]"
    sql = f"""
        SELECT
            CAST(Date_Time AS DATE) AS date,
            COUNT(*) AS total_records,
            SUM(CASE WHEN UPPER(COALESCE(Stn_Status,'')) = 'REJECTED'
                     OR NULLIF(LTRIM(RTRIM(COALESCE(Rejected_Reason,''))), '') IS NOT NULL
                     THEN 1 ELSE 0 END) AS failures,
            SUM(ISNULL(TRY_CAST(ReworkCount AS INT), 0)) AS reworks,
            COUNT(DISTINCT Engine_Number) AS engines_processed
        FROM {table}
        WHERE Date_Time >= DATEADD(DAY, -{days}, GETDATE())
        GROUP BY CAST(Date_Time AS DATE)
        ORDER BY date ASC
    """

    df = await asyncio.get_event_loop().run_in_executor(
        executor, lambda: run_query(sql, ())
    )
    result = {"data": _df_to_records(df), "row_count": len(df), "cached": False}
    _cache_set(cache_key, result)
    return result


def _build_date_clause(req: AnalyticsRequest):
    params = []
    clauses = []
    if req.date_from:
        clauses.append("Date_Time >= ?")
        params.append(req.date_from)
    elif req.days:
        clauses.append(f"Date_Time >= DATEADD(DAY, -{req.days}, GETDATE())")
    if req.date_to:
        clauses.append("Date_Time < ?")
        params.append(req.date_to)
    if clauses:
        return "WHERE " + " AND ".join(clauses), params
    return "", params


@app.post("/export/csv")
async def export_csv(req: ChatRequest):
    result = await chat(req)
    if result.get("status") != "success" or not result.get("data"):
        raise HTTPException(status_code=404, detail=result.get("message", "No data"))

    df = pd.DataFrame(result["data"])
    csv_content = df.to_csv(index=False)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=engine_history.csv"},
    )
