from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from google import genai

# =========================================================
# ENV
# =========================================================
load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is missing. Put it in your .env file and make sure load_dotenv() runs."
    )

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# =========================================================
# GEMINI INIT
# =========================================================
client = genai.Client(api_key=GEMINI_API_KEY)

# =========================================================
# SAFE CALL (RETRY)
# =========================================================
def safe_generate(prompt: str, retries: int = 3) -> str:
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            text = getattr(response, "text", None)
            if text is None:
                raise RuntimeError("Gemini returned an empty response.")
            return text
        except Exception as e:
            last_error = e
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))

    raise last_error or RuntimeError("Gemini call failed unexpectedly.")

# =========================================================
# JSON CLEAN
# =========================================================
def clean_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"```json|```", "", text).strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)

    return json.loads(text)

# =========================================================
# CHAT INTENT CLASSIFIER
# =========================================================
def classify_chat_intent(user_query: str) -> str:
    """
    Returns one of:
    - greeting
    - casual_question
    - data_query
    - unknown
    """
    prompt = f"""
You are classifying a user message for an engine-history assistant.

Choose exactly one label:
- greeting
- casual_question
- data_query
- unknown

Rules:
- greeting = hi, hello, hey, good morning, good afternoon, good evening
- casual_question = what can you do, help, who are you, how does this work, options, features
- data_query = asks for engine data, station data, barcode, torque, leak, status, summary, timeline, failure, rework, rejection, analytics
- unknown = anything else

User message:
{user_query}

Return JSON only:
{{"intent_type":"..."}}
"""
    try:
        raw = safe_generate(prompt)
        data = clean_json(raw)
        intent = str(data.get("intent_type", "unknown")).strip().lower()
        if intent in {"greeting", "casual_question", "data_query", "unknown"}:
            return intent
    except Exception:
        pass
    return "unknown"

# =========================================================
# SIMPLE CHAT REPLY
# =========================================================
def answer_chat_message(user_query: str) -> str:
    prompt = f"""
You are Engine Intelligence, an assistant for a manufacturing history-card system.

Your job:
- If the user greets you, introduce yourself briefly.
- If the user asks a general question, explain what you can do.
- If the user asks for database data but did not provide enough details, ask for the missing details.
- Keep the answer short, clear, and useful.

User message:
{user_query}
"""
    try:
        return safe_generate(prompt).strip()
    except Exception:
        return "Hi! I’m Engine Intelligence. I can help with engine summaries, timelines, barcode, torque, leak, station status, and analytics."

# =========================================================
# PLAN REFINER
# =========================================================
def refine_plan_with_gemini(
    user_query: str,
    seed_plan: Dict[str, Any],
    station_guide: str,
    schema_columns: list[str],
) -> Dict[str, Any]:
    """
    Refines a structured plan using Gemini.
    Returns a merged plan with Gemini overrides.
    """
    prompt = f"""
You are refining a structured plan for a manufacturing engine-history chatbot.

Database facts:
- Each engine moves through many stations (ML-01 to ML-54)
- Data is row-wise
- Schema is wide
- Never invent columns
- Do NOT generate SQL
- Return JSON only

Station master guide:
{station_guide}

Schema columns:
{", ".join(schema_columns[:200])}

User query:
{user_query}

Seed plan:
{json.dumps(seed_plan, indent=2)}

Return JSON:
{{
  "intent": "",
  "engine_numbers": [],
  "station": null,
  "parameter": null,
  "columns_requested": [],
  "date_from": null,
  "date_to": null,
  "employee": null,
  "needs_clarification": false,
  "clarification_question": null
}}
"""
    try:
        response = safe_generate(prompt)
        plan = clean_json(response)
    except Exception:
        return seed_plan

    merged = dict(seed_plan)
    merged.update({k: v for k, v in plan.items() if v not in [None, "", []]})
    return merged