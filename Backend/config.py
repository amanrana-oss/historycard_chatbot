from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()

DEFAULT_SOURCE_NAME = os.getenv(
    "HISTORYCARD_DEFAULT_SOURCE_NAME",
    "mainline_history_card",
)

PROJECT_ID = os.getenv("PROJECT_ID", "re-platform-sap-gemini-poc")
LOCATION = os.getenv("LOCATION", "us-central1")
GEMINI_PROJECT_ID = PROJECT_ID
GEMINI_LOCATION = LOCATION

GEMINI_SERVICE_ACCOUNT_FILE = os.getenv(
    "GEMINI_SERVICE_ACCOUNT_FILE",
    str(BASE_DIR / "service_account.json")
)

SERVICE_ACCOUNT_FILE = GEMINI_SERVICE_ACCOUNT_FILE

DB_SERVER = os.getenv("HISTORYCARD_DB_SERVER", "10.130.1.73")
DB_NAME = os.getenv("HISTORYCARD_DB_DATABASE", "RE_Vallam_J1EA2_Mainline_DB")
DB_USER = os.getenv("HISTORYCARD_DB_USERNAME", "factreread")
DB_PASSWORD = os.getenv("HISTORYCARD_DB_PASSWORD", "factreread")

DB_DRIVER = os.getenv("HISTORYCARD_DB_DRIVER", "SQL Server")

_table_name = os.getenv(
    "HISTORYCARD_DB_TABLE",
    "dbo.STN_data",
)
if "." in _table_name:
    TABLE_SCHEMA, TABLE_NAME = _table_name.split(".", 1)
else:
    TABLE_SCHEMA = os.getenv("TABLE_SCHEMA", "dbo")
    TABLE_NAME = _table_name

TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
IST_TIMEZONE = TIMEZONE

SUPPORTED_INTENTS = [
    "engine_summary",
    "engine_timeline",
    "station_detail",
    "station_parameter_query",
    "column_query",
    "failure_summary",
    "first_failure",
    "rework_summary",
    "rejection_summary",
    "latest_status",
    "compare_engines",
    "date_range_history",
    "employee_activity",
    "checkpoint_detail",
    "raw_station_row",
    "station_failures",
    "rejection_reasons",
    "rework_stations",
    "failure_trend",
    "unknown",
]