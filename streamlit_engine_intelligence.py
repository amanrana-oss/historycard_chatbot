import io
import math
from datetime import date

import pandas as pd
import requests
import streamlit as st

BASE_URL = "http://localhost:8000"
PAGE_SIZE = 50

st.set_page_config(
    page_title="Engine History Intelligence",
    page_icon="⚙",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp { background: #080c18; color: #e2e8f0; }
    [data-testid="stSidebar"] { background: #0d1221; border-right: 1px solid #1f2d45; }
    .app-title { font-family: monospace; letter-spacing: .08em; text-transform: uppercase; font-size: 13px; color: #06b6d4; margin-bottom: 2px; }
    .app-subtitle { color: #8892a4; font-size: 12px; margin-bottom: 12px; }
    .card { background: #111827; border: 1px solid #1f2d45; border-radius: 12px; padding: 16px; margin-bottom: 8px; }
    .card h3 { font-family: monospace; font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #8892a4; margin: 0 0 12px 0; }
    .status-badge { display:inline-flex; align-items:center; gap:6px; padding:4px 9px; border-radius:999px; font-size:11px; font-weight:700; font-family: monospace; border:1px solid transparent; margin-right:6px; margin-bottom:6px; }
    .badge-ok { background: rgba(16,185,129,.12); color: #10b981; border-color: rgba(16,185,129,.22); }
    .badge-warn { background: rgba(245,158,11,.12); color: #f59e0b; border-color: rgba(245,158,11,.22); }
    .badge-error { background: rgba(239,68,68,.12); color: #ef4444; border-color: rgba(239,68,68,.22); }
    .badge-info { background: rgba(37,99,235,.12); color: #60a5fa; border-color: rgba(37,99,235,.22); }
    .msg-wrap { margin-bottom: 14px; }
    .msg-meta { font-size: 10px; color: #4a5568; font-family: monospace; margin-bottom: 6px; }
    .bubble-user { background: #2563eb; color: white; padding: 10px 14px; border-radius: 12px 12px 2px 12px; max-width: 75%; margin-left: auto; font-size: 13px; line-height: 1.5; }
    .bubble-assistant { background: #111827; border: 1px solid #1f2d45; padding: 14px 16px; border-radius: 2px 12px 12px 12px; max-width: 100%; font-size: 13px; }
    .assistant-topline { display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-bottom:10px; }
    .assistant-message { margin: 10px 0; padding: 10px 12px; border-radius: 8px; border: 1px solid rgba(245,158,11,.2); background: rgba(245,158,11,.08); color: #f59e0b; line-height: 1.55; font-size: 13px; }
    .assistant-message.is-error { border-color: rgba(239,68,68,.2); background: rgba(239,68,68,.08); color: #ef4444; }
    .sidebar-logo h1 { font-family: monospace; font-size: 13px; font-weight: 700; color: #06b6d4; letter-spacing: .08em; margin: 0; text-transform: uppercase; }
    .sidebar-logo p { font-size: 11px; color: #4a5568; margin: 3px 0 0 0; font-family: monospace; }
    .sidebar-section-title { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: #4a5568; font-family: monospace; margin-top: 18px; margin-bottom: 8px; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)


def api_request(method, path, payload=None, timeout=30):
    url = f"{BASE_URL}{path}"
    try:
        if method.upper() == "GET":
            res = requests.get(url, timeout=timeout)
        else:
            res = requests.request(method.upper(), url, json=payload, timeout=timeout)

        if not res.ok:
            try:
                detail = res.json().get("detail") or res.text
            except Exception:
                detail = res.text or f"HTTP {res.status_code}"
            return {"status": "error", "message": f"Connection error: {detail}", "data": [], "columns": [], "row_count": 0}

        try:
            return res.json()
        except Exception:
            return res.content
    except requests.RequestException as exc:
        return {"status": "error", "message": f"Connection error: {exc}", "data": [], "columns": [], "row_count": 0}


@st.cache_data(ttl=60)
def get_stations():
    res = api_request("GET", "/stations")
    if isinstance(res, dict):
        return res.get("stations", [])
    return []


@st.cache_data(ttl=60)
def fetch_analytics(endpoint, days):
    mapping = {
        "station-failures": "/analytics/station-failures",
        "rejection-reasons": "/analytics/rejection-reasons",
        "rework-stations": "/analytics/rework-stations",
        "failure-trend": "/analytics/failure-trend",
    }
    return api_request("POST", mapping[endpoint], {"query_type": endpoint.replace("-", "_"), "days": days})


def make_quick_query(param, station, date_from, date_to):
    if not param or param == "(choose)":
        return None
    station_part = f" for {station}" if station and station != "(all)" else ""
    if date_from and date_to:
        if str(date_from) == str(date_to):
            date_part = f" on {date_from}"
        else:
            date_part = f" from {date_from} to {date_to}"
    else:
        date_part = " today"
    return f"show {param}{station_part}{date_part}"


def df_from_result(result):
    if isinstance(result, list):
        return pd.DataFrame(result)
    if isinstance(result, dict):
        if "data" in result and isinstance(result["data"], list):
            return pd.DataFrame(result["data"])
        return pd.DataFrame([result])
    return pd.DataFrame()


def status_badge(status):
    mapping = {
        "success": ("badge-ok", "✓ Data found"),
        "empty": ("badge-warn", "⚠ No data"),
        "error": ("badge-error", "✗ Error"),
        "not_found": ("badge-error", "✗ Not found"),
        "clarification": ("badge-info", "? Clarification needed"),
    }
    cls, label = mapping.get(status, ("badge-info", status or "info"))
    return f'<span class="status-badge {cls}">{label}</span>'


def render_paginated_table(df, key_prefix):
    if df is None or df.empty:
        st.caption("No rows returned.")
        return

    total_rows = len(df)
    total_pages = max(1, math.ceil(total_rows / PAGE_SIZE))
    page_key = f"{key_prefix}_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0
    if st.session_state[page_key] >= total_pages:
        st.session_state[page_key] = total_pages - 1

    page = st.session_state[page_key]
    rows = df.iloc[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    if total_pages > 1:
        c1, c2, c3, c4, c5 = st.columns([1, 1, 2, 1, 1])
        with c1:
            if st.button("«", key=f"{key_prefix}_first", use_container_width=True):
                st.session_state[page_key] = 0
                st.rerun()
        with c2:
            if st.button("‹", key=f"{key_prefix}_prev", use_container_width=True):
                st.session_state[page_key] = max(0, page - 1)
                st.rerun()
        with c3:
            st.markdown(
                f"<div style='text-align:center;color:#8892a4;font-family:monospace;font-size:11px;padding-top:6px;'>{page + 1} / {total_pages} · {total_rows} rows</div>",
                unsafe_allow_html=True,
            )
        with c4:
            if st.button("›", key=f"{key_prefix}_next", use_container_width=True):
                st.session_state[page_key] = min(total_pages - 1, page + 1)
                st.rerun()
        with c5:
            if st.button("»", key=f"{key_prefix}_last", use_container_width=True):
                st.session_state[page_key] = total_pages - 1
                st.rerun()


def result_to_csv_bytes(msg, fallback_df=None):
    export_state = msg.get("export_state") or {}
    question = export_state.get("question")
    filters = export_state.get("filters", {})
    if question:
        export = api_request(
            "POST",
            "/export/csv",
            {
                "question": question,
                "station_filter": filters.get("station_filter"),
                "date_from": filters.get("date_from"),
                "date_to": filters.get("date_to"),
            },
            timeout=60,
        )
        if isinstance(export, (bytes, bytearray)):
            return bytes(export)

    if fallback_df is not None:
        buf = io.StringIO()
        fallback_df.to_csv(buf, index=False)
        return buf.getvalue().encode("utf-8")

    return b""


def process_question(question):
    filters = st.session_state.get("filters", {})
    station = None if filters.get("station") in (None, "(all)") else filters.get("station")
    payload = {
        "question": question,
        "station_filter": station,
        "date_from": None,
        "date_to": None,
    }

    st.session_state.messages.append({"role": "user", "content": question})
    result = api_request("POST", "/chat", payload)

    if isinstance(result, dict) and "status" not in result:
        result = {
            "status": "success",
            "message": result.get("message", ""),
            "data": result.get("data", []) if isinstance(result.get("data"), list) else [],
            "columns": result.get("columns", []) or [],
            "row_count": result.get("row_count", 0),
            "cached": result.get("cached", False),
            "meta": result.get("meta", {}),
            "query_ms": result.get("query_ms"),
        }

    st.session_state.messages.append(
        {
            "role": "assistant",
            "question": question,
            "result": result,
            "export_state": {
                "question": question,
                "filters": {
                    "station_filter": station,
                    "date_from": None,
                    "date_to": None,
                },
            },
        }
    )


def render_chat_message(msg, idx):
    if msg["role"] == "user":
        st.markdown(
            f'<div class="msg-wrap"><div class="msg-meta">You</div><div class="bubble-user">{msg["content"]}</div></div>',
            unsafe_allow_html=True,
        )
        return

    result = msg.get("result") or {}
    status = result.get("status", "info")
    row_count = result.get("row_count", 0)
    columns = result.get("columns") or []
    cached = result.get("cached", False)
    meta = result.get("meta") or {}
    message = result.get("message") or ""
    query_ms = result.get("query_ms")

    meta_bits = []
    if row_count is not None:
        meta_bits.append(f"{row_count} row{'s' if row_count != 1 else ''}")
    if columns:
        meta_bits.append(f"{len(columns)} cols")
    if cached:
        meta_bits.append("cached")
    if query_ms is not None:
        meta_bits.append(f"~{query_ms}ms")

    badges = [status_badge(status)]
    if meta.get("parameter"):
        badges.append(f'<span class="status-badge badge-info">{meta["parameter"]}</span>')

    meta_html = "".join(
        [f"<span style='font-size:10px;color:#4a5568;font-family:monospace;'>{b}</span>" for b in meta_bits]
    )

    st.markdown(
        f"""
        <div class="msg-wrap">
          <div class="msg-meta">Engine Intelligence</div>
          <div class="bubble-assistant">
            <div class="assistant-topline">{''.join(badges)}{meta_html}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if message:
        is_error = status in {"error", "not_found", "empty", "clarification"}
        st.markdown(
            f'<div class="assistant-message {"is-error" if is_error else ""}">{message}</div>',
            unsafe_allow_html=True,
        )

    if result.get("data"):
        df = df_from_result(result["data"])
        if not df.empty:
            render_paginated_table(df, key_prefix=f"msg_{idx}")
            csv_bytes = result_to_csv_bytes(msg, fallback_df=df)
            st.download_button(
                "Download CSV",
                data=csv_bytes,
                file_name="engine_history.csv",
                mime="text/csv",
                key=f"download_{idx}",
                use_container_width=False,
            )


def normalize_analytics_frame(result):
    if isinstance(result, dict) and "data" in result and isinstance(result["data"], list):
        return pd.DataFrame(result["data"])
    if isinstance(result, list):
        return pd.DataFrame(result)
    return pd.DataFrame()


if "messages" not in st.session_state:
    st.session_state.messages = []
if "filters" not in st.session_state:
    today = str(date.today())
    st.session_state.filters = {"station": "(all)", "param": "(choose)", "dateFrom": today, "dateTo": today}
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "CHAT"
if "analytics_days" not in st.session_state:
    st.session_state.analytics_days = 7
if "queued_question" not in st.session_state:
    st.session_state.queued_question = None


stations = get_stations()

with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-logo">
            <h1>⚙ Engine Intelligence</h1>
            <p>Assembly History System v2</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="sidebar-section-title">Quick Filters</div>', unsafe_allow_html=True)

    station_list = ["(all)"] + stations
    station_default = st.session_state.filters.get("station", "(all)")
    station_index = station_list.index(station_default) if station_default in station_list else 0
    station = st.selectbox("Station", station_list, index=station_index)

    param_list = ["(choose)", "barcode", "torque", "leak", "status"]
    param_default = st.session_state.filters.get("param", "(choose)")
    param_index = param_list.index(param_default) if param_default in param_list else 0
    param = st.selectbox("Parameter", param_list, index=param_index)

    c1, c2 = st.columns(2)
    with c1:
        date_from = st.date_input("Date From", value=date.fromisoformat(st.session_state.filters.get("dateFrom") or str(date.today())))
    with c2:
        date_to = st.date_input("Date To", value=date.fromisoformat(st.session_state.filters.get("dateTo") or str(date.today())))

    st.session_state.filters.update({"station": station, "param": param, "dateFrom": str(date_from), "dateTo": str(date_to)})

    if st.button("▶ Run Quick Query", use_container_width=True):
        q = make_quick_query(param, station, date_from, date_to)
        if not q:
            st.warning("Pick a parameter first.")
        else:
            st.session_state.active_tab = "CHAT"
            st.session_state.queued_question = q
            st.rerun()

    st.markdown('<div class="sidebar-section-title">Examples</div>', unsafe_allow_html=True)
    examples = [
        "summary of engine J3A5FNS2048940",
        "show timeline of engine J3A5FNS2048940",
        "barcode for ML-50 today",
        "torque value of ML-10 today",
        "leak value today",
        "show all barcodes this week",
        "torque for ML-43 yesterday",
        "station status for ML-47 today",
        "show first failure of engine J3A5FNS2048940",
        "compare engine J3A5FNS2048940 and J3A5FNS2048941",
        "show ML-39 details for engine J3A5FNS2048940",
    ]

    for i, ex in enumerate(examples):
        if st.button(ex, key=f"example_{i}", use_container_width=True):
            st.session_state.active_tab = "CHAT"
            st.session_state.queued_question = ex
            st.rerun()

    st.markdown(
        """
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid #1f2d45;color:#4a5568;font-family:monospace;font-size:10px;line-height:1.5;">
            Queries are cached for 60s.<br/>
            100+ concurrent users supported.
        </div>
        """,
        unsafe_allow_html=True,
    )

queued = st.session_state.get("queued_question")
if queued:
    st.session_state.queued_question = None
    process_question(queued)
    st.rerun()


st.markdown(
    """
    <div class="app-title">ENGINE HISTORY INTELLIGENCE</div>
    <div class="app-subtitle">Ask natural language questions about engine assembly history, station data, barcode scans, torque values, and production analytics.</div>
    """,
    unsafe_allow_html=True,
)

tabs = st.radio(
    label="Navigation",
    options=["CHAT", "ANALYTICS"],
    horizontal=True,
    label_visibility="collapsed",
    key="active_tab",
)
tab1, tab2 = st.tabs(["💬 Chat", "📊 Analytics"])
if tabs == "CHAT":
    if not st.session_state.messages:
        st.markdown(
            """
            <div class="card" style="text-align:center;padding:42px 20px;">
                <div style="font-size:48px;opacity:.3;">⚙</div>
                <div style="font-family:monospace;font-size:16px;color:#8892a4;letter-spacing:0.05em;margin-top:8px;">
                    ENGINE HISTORY INTELLIGENCE
                </div>
                <div style="color:#4a5568;font-size:13px;max-width:520px;margin:12px auto 0;line-height:1.7;">
                    Ask natural language questions about engine assembly history,
                    station data, barcode scans, torque values, leak values, station failures, and production analytics.
                </div>
                <div style="font-family:monospace;font-size:11px;color:#4a5568;margin-top:10px;">
                    Try: "barcode for ML-50 today" or "torque for ML-43 yesterday"
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    for idx, msg in enumerate(st.session_state.messages):
        render_chat_message(msg, idx)

    question = st.chat_input("Ask about engine history, barcodes, torque, leak values, or station status...")
    if question and question.strip():
        process_question(question.strip())
        st.rerun()

else:
    st.markdown(
        """
        <div style="margin-bottom:8px;">
            <div style="font-family:monospace;font-size:13px;color:#8892a4;letter-spacing:0.06em;">PRODUCTION ANALYTICS</div>
            <div style="color:#4a5568;font-size:12px;margin-top:4px;">Real-time insights from the assembly line</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    days = st.radio("Last days", [7, 14, 30], horizontal=True, index=[7, 14, 30].index(st.session_state.analytics_days), key="analytics_days_radio")
    st.session_state.analytics_days = days

    failures_res = fetch_analytics("station-failures", days)
    reasons_res = fetch_analytics("rejection-reasons", days)
    rework_res = fetch_analytics("rework-stations", days)
    trend_res = fetch_analytics("failure-trend", days)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="card"><h3>Which station fails the most?</h3>', unsafe_allow_html=True)
        if isinstance(failures_res, dict) and failures_res.get("status") == "error":
            st.error(failures_res.get("message", "Unknown error"))
        else:
            df = normalize_analytics_frame(failures_res)
            if df.empty:
                st.caption("No failure data found.")
            else:
                chart_df = df.head(10).copy()
                if {"Stn_Number", "failure_count"}.issubset(chart_df.columns):
                    st.bar_chart(chart_df.set_index("Stn_Number")["failure_count"])
                st.dataframe(chart_df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="card"><h3>Top rejection reasons this week</h3>', unsafe_allow_html=True)
        if isinstance(reasons_res, dict) and reasons_res.get("status") == "error":
            st.error(reasons_res.get("message", "Unknown error"))
        else:
            df = normalize_analytics_frame(reasons_res)
            if df.empty:
                st.caption("No rejection data found.")
            else:
                chart_df = df.head(8).copy()
                if {"reason", "count"}.issubset(chart_df.columns):
                    st.bar_chart(chart_df.set_index("reason")["count"])
                st.dataframe(chart_df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

    c3, c4 = st.columns(2)
    with c3:
        st.markdown('<div class="card"><h3>Which ML station causes max rework?</h3>', unsafe_allow_html=True)
        if isinstance(rework_res, dict) and rework_res.get("status") == "error":
            st.error(rework_res.get("message", "Unknown error"))
        else:
            df = normalize_analytics_frame(rework_res)
            if df.empty:
                st.caption("No rework data found.")
            else:
                chart_df = df.head(10).copy()
                if {"Stn_Number", "total_rework"}.issubset(chart_df.columns):
                    st.bar_chart(chart_df.set_index("Stn_Number")["total_rework"])
                st.dataframe(chart_df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with c4:
        st.markdown(f'<div class="card"><h3>Failure trend over last {days} days</h3>', unsafe_allow_html=True)
        if isinstance(trend_res, dict) and trend_res.get("status") == "error":
            st.error(trend_res.get("message", "Unknown error"))
        else:
            df = normalize_analytics_frame(trend_res)
            if df.empty:
                st.caption("No trend data found.")
            else:
                chart_df = df.copy()
                if "date" in chart_df.columns:
                    chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
                    chart_df = chart_df.sort_values("date").set_index("date")
                    cols_to_plot = [c for c in ["failures", "reworks", "engines_processed"] if c in chart_df.columns]
                    if cols_to_plot:
                        st.line_chart(chart_df[cols_to_plot])
                st.dataframe(df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
