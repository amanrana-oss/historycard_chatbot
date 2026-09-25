from __future__ import annotations

import re
from datetime import datetime, timedelta, time as dtime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

import config
from gemini_agent import refine_plan_with_gemini
from station_rules import build_station_guide, normalize_station

IST = ZoneInfo(config.IST_TIMEZONE)

PARAMETER_KEYWORDS = {
    "barcode": [r"\bbar\s*code(s)?\b", r"\bbarcode(s)?\b"],
    "leak": [r"\bleak(s)?\b", r"\bleak\s*value(s)?\b"],
    "torque": [r"\btorque(s)?\b", r"\btorque\s*value(s)?\b"],
    "status": [r"\bstation\s*status\b", r"\bstatus\b"],
}

ANALYTICS_PATTERNS = {
    "station_failures": [
        r"\bwhich\s+station\s+fail", r"\bstation.*fail.*most\b",
        r"\bmost\s+fail", r"\bfail.*most", r"\btop.*fail.*station",
    ],
    "rejection_reasons": [
        r"\btop\s+rejection", r"\brejection\s+reason", r"\bwhy.*reject",
        r"\bcommon.*reject", r"\brejected.*reason",
    ],
    "rework_stations": [
        r"\bwhich.*station.*rework", r"\bmax.*rework", r"\bmost.*rework",
        r"\brework.*station", r"\bcause.*rework",
    ],
    "failure_trend": [
        r"\bfailure\s+trend", r"\btrend.*fail", r"\bfail.*trend",
        r"\bfailures?\s+over\s+", r"\blast\s+\d+\s+day", r"\bweekly\s+fail",
    ],
}


def _dedupe_keep_order(items: List[str]) -> List[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def extract_station(text: str) -> Optional[str]:
    m = re.search(r"\bML[-\s]?(\d{1,2})\b", text.upper())
    if not m:
        return None
    return f"ML-{int(m.group(1)):02d}"


def extract_engine_numbers(text: str) -> List[str]:
    t = text.upper()
    engines: List[str] = []

    for m in re.finditer(
        r"ENGINE(?:\s+NUMBER)?(?:\s*(?:IS|=|:|OF|FOR)?)\s*([A-Z0-9-]{8,25})", t
    ):
        val = m.group(1).strip(" ,.;:()[]{}")
        if (
            val
            and not val.startswith("ML-")
            and any(ch.isalpha() for ch in val)
            and any(ch.isdigit() for ch in val)
        ):
            engines.append(val)

    if not engines:
        tokens = re.findall(r"\b[A-Z0-9-]{8,25}\b", t)
        for tok in tokens:
            if tok.startswith("ML-"):
                continue
            if any(ch.isalpha() for ch in tok) and any(ch.isdigit() for ch in tok):
                engines.append(tok)

    return _dedupe_keep_order(engines)[:2]


def extract_parameter(text: str) -> Optional[str]:
    q = text.lower()
    for parameter, patterns in PARAMETER_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, q, re.I):
                return parameter
    return None


def _parse_single_date(value: str) -> datetime:
    value = value.strip()

    #  If format is YYYY-MM-DD → DO NOT use dateparser
    if re.match(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.strptime(value, "%Y-%m-%d")

    # fallback
    dt = dateparser.parse(value, dayfirst=True, fuzzy=True)
    if dt is None:
        raise ValueError(f"Could not parse date: {value}")
    return dt


def extract_date_range(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    q = text.lower()
    now = datetime.now(IST)

    if "today" in q:
        start = datetime.combine(now.date(), dtime.min).replace(tzinfo=IST)
        end = start + timedelta(days=1)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "today"

    if "yesterday" in q:
        start = datetime.combine((now.date() - timedelta(days=1)), dtime.min).replace(tzinfo=IST)
        end = start + timedelta(days=1)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "yesterday"

    if "this week" in q:
        start_of_week = now.date() - timedelta(days=now.weekday())
        start = datetime.combine(start_of_week, dtime.min).replace(tzinfo=IST)
        end = start + timedelta(days=7)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "this_week"

    if "last week" in q:
        start_of_week = now.date() - timedelta(days=now.weekday() + 7)
        start = datetime.combine(start_of_week, dtime.min).replace(tzinfo=IST)
        end = start + timedelta(days=7)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "last_week"

    if "this month" in q:
        start = datetime(now.year, now.month, 1, tzinfo=IST)
        end = (
            datetime(now.year + 1, 1, 1, tzinfo=IST)
            if now.month == 12
            else datetime(now.year, now.month + 1, 1, tzinfo=IST)
        )
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "this_month"

    if "last month" in q:
        if now.month == 1:
            start = datetime(now.year - 1, 12, 1, tzinfo=IST)
            end = datetime(now.year, 1, 1, tzinfo=IST)
        else:
            start = datetime(now.year, now.month - 1, 1, tzinfo=IST)
            end = datetime(now.year, now.month, 1, tzinfo=IST)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "last_month"

    m = re.search(r"last\s+(\d+)\s+days?", q)
    if m:
        n = int(m.group(1))
        start = datetime.combine((now.date() - timedelta(days=n)), dtime.min).replace(tzinfo=IST)
        end = datetime.combine(now.date(), dtime.min).replace(tzinfo=IST) + timedelta(days=1)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), f"last_{n}_days"

    date_regex = r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    matches = re.findall(date_regex, text)
    if len(matches) == 1:
        dt = _parse_single_date(matches[0])
        start = datetime.combine(dt.date(), dtime.min).replace(tzinfo=IST)
        end = start + timedelta(days=1)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "explicit_date"

    if len(matches) >= 2:
        d1 = _parse_single_date(matches[0])
        d2 = _parse_single_date(matches[1])
        start_date = min(d1.date(), d2.date())
        end_date = max(d1.date(), d2.date())
        start = datetime.combine(start_date, dtime.min).replace(tzinfo=IST)
        end = datetime.combine(end_date, dtime.min).replace(tzinfo=IST) + timedelta(days=1)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "explicit_range"

    return None, None, None


def _detect_analytics_intent(q: str) -> Optional[str]:
    low = q.lower()
    for intent, patterns in ANALYTICS_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, low):
                return intent
    return None


def _detect_simple_chat_intent(q: str) -> Optional[str]:
    low = q.lower().strip()

    if re.match(r"^(hi|hello|hey|hii|good morning|good afternoon|good evening)\b", low):
        return "greeting"

    if re.search(r"\b(what can you do|help|how can you help|who are you|about you|options|features)\b", low):
        return "casual_question"

    return None


def _detect_intent(
    q: str,
    engines: List[str],
    station: Optional[str],
    parameter: Optional[str],
    date_from: Optional[str],
) -> str:
    low = q.lower()

    chat_intent = _detect_simple_chat_intent(q)
    if chat_intent:
        return chat_intent

    analytics = _detect_analytics_intent(q)
    if analytics:
        return analytics

    if "compare" in low and len(engines) >= 2:
        return "compare_engines"

    if any(k in low for k in ["summary", "summarize", "overall summary"]) and (engines or "engine" in low):
        return "engine_summary"

    if any(k in low for k in ["timeline", "history", "journey", "full history"]):
        return "engine_timeline"

    if any(k in low for k in ["first failure", "first issue", "first rejection"]):
        return "first_failure"

    if any(k in low for k in ["latest status", "current status", "last status", "most recent status"]):
        return "latest_status"

    if "rework" in low:
        return "rework_summary"

    if any(k in low for k in ["reject", "rejection"]):
        return "rejection_summary"

    if parameter in {"barcode", "torque", "leak", "status"}:
        return "station_parameter_query"

    if station and any(k in low for k in ["what happened", "station detail", "details", "show row", "raw row"]):
        return "station_detail"

    return "unknown"


def _needs_clarification(
    intent: str,
    engines: List[str],
    station: Optional[str],
    date_from: Optional[str],
    parameter: Optional[str],
) -> Tuple[bool, Optional[str]]:
    if intent == "station_parameter_query":
        if not engines and not station and not date_from:
            return True, (
                "Please specify at least one filter: engine, station, or date."
            )
    return False, None


def parse_question(user_query: str, schema_columns: List[str]) -> Dict[str, Any]:
    q = user_query.strip()
    station = extract_station(q)
    engines = extract_engine_numbers(q)
    parameter = extract_parameter(q)
    date_from, date_to, date_label = extract_date_range(q)
    intent = _detect_intent(q, engines, station, parameter, date_from)

    needs_clarification, clarification_question = _needs_clarification(
        intent, engines, station, date_from, parameter
    )

    plan: Dict[str, Any] = {
        "intent": intent,
        "engine_numbers": engines,
        "station": station,
        "parameter": parameter,
        "columns_requested": [parameter] if parameter else [],
        "date_from": date_from,
        "date_to": date_to,
        "employee": None,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "date_label": date_label,
    }

    if needs_clarification:
        return plan

    if intent == "unknown":
        station_guide = build_station_guide()
        try:
            refined = refine_plan_with_gemini(q, plan, station_guide, schema_columns)
            plan.update(refined)
        except Exception:
            pass

        chat_intent = _detect_simple_chat_intent(q)
        if chat_intent:
            plan["intent"] = chat_intent

    return plan