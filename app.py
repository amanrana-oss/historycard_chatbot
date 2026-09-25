import streamlit as st
import requests
from datetime import date

BASE_URL = "http://localhost:8000"

# ---------------- API ----------------
def api_post(path, payload):
    res = requests.post(f"{BASE_URL}{path}", json=payload)
    if res.status_code != 200:
        return {"status": "error", "message": res.text}
    return res.json()

def get_stations():
    try:
        return requests.get(f"{BASE_URL}/stations").json().get("stations", [])
    except:
        return []

# ---------------- SESSION ----------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "filters" not in st.session_state:
    today = str(date.today())
    st.session_state.filters = {
        "station": "(all)",
        "dateFrom": today,
        "dateTo": today
    }

if "tab" not in st.session_state:
    st.session_state.tab = "chat"

# ---------------- SIDEBAR ----------------
st.sidebar.title("⚙ Engine Intelligence")

stations = get_stations()

station = st.sidebar.selectbox(
    "Station",
    ["(all)"] + stations,
    index=0
)

date_from = st.sidebar.date_input("Date From", value=date.today())
date_to = st.sidebar.date_input("Date To", value=date.today())

st.session_state.filters.update({
    "station": station,
    "dateFrom": str(date_from),
    "dateTo": str(date_to)
})

st.sidebar.markdown("---")

# Example queries
examples = [
    "barcode for ML-50 today",
    "torque value of ML-10 today",
    "leak value today",
    "which station fails the most"
]

for ex in examples:
    if st.sidebar.button(ex):
        st.session_state.input = ex
        st.session_state.tab = "chat"

# ---------------- TABS ----------------
tab1, tab2 = st.tabs(["💬 Chat", "📊 Analytics"])

# ---------------- CHAT ----------------
with tab1:
    st.title("Engine Chat")

    # Show messages
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.chat_message("user").write(msg["content"])
        else:
            with st.chat_message("assistant"):
                result = msg["result"]

                if result.get("message"):
                    st.warning(result["message"])

                if result.get("data"):
                    st.dataframe(result["data"])

    # Input
    user_input = st.chat_input("Ask question")

    if user_input:
        st.session_state.messages.append({
            "role": "user",
            "content": user_input
        })

        with st.spinner("Thinking..."):
            res = api_post("/chat", {
                "question": user_input,
                "station_filter": None if station == "(all)" else station,
                "date_from": None,
                "date_to": None
            })

        st.session_state.messages.append({
            "role": "assistant",
            "result": res
        })

        st.rerun()

# ---------------- ANALYTICS ----------------
with tab2:
    st.title("Analytics")

    days = st.selectbox("Days", [7, 14, 30], index=0)

    col1, col2 = st.columns(2)

    # ---- Station Failures ----
    with col1:
        st.subheader("Station Failures")
        res = api_post("/analytics/station-failures", {
            "query_type": "station_failures",
            "days": days
        })
        if res:
            st.dataframe(res)

    # ---- Rejection Reasons ----
    with col2:
        st.subheader("Rejection Reasons")
        res = api_post("/analytics/rejection-reasons", {
            "query_type": "rejection_reasons",
            "days": days
        })
        if res:
            st.dataframe(res)

    col3, col4 = st.columns(2)

    # ---- Rework ----
    with col3:
        st.subheader("Rework Stations")
        res = api_post("/analytics/rework-stations", {
            "query_type": "rework_stations",
            "days": days
        })
        if res:
            st.dataframe(res)

    # ---- Trend ----
    with col4:
        st.subheader("Failure Trend")
        res = api_post("/analytics/failure-trend", {
            "query_type": "failure_trend",
            "days": days
        })
        if res:
            st.dataframe(res)