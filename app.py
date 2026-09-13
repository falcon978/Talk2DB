"""
Streamlit UI for the Talk2DB.

This is a thin presentation layer. All backend logic lives in the
talk2db package and is initialized via lifecycle.startup().
To swap to FastAPI, simply import lifecycle in a FastAPI app instead.
"""

import streamlit as st
import uuid
import time
import requests
from config import config
from talk2db.logger import get_logger

logger = get_logger(__name__)

API_URL = config.api_url

# --- Streamlit Config & Premium CSS ---
st.set_page_config(
    page_title=config.ui_page_title, layout="wide", initial_sidebar_state="expanded"
)


def load_css():
    """Injects premium dark-mode glassmorphism styling."""
    st.markdown("""
        <style>
        .stApp {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #f8fafc;
            font-family: 'Inter', sans-serif;
        }
        .stSidebar {
            background: rgba(15, 23, 42, 0.6) !important;
            backdrop-filter: blur(12px);
            border-right: 1px solid rgba(255,255,255,0.05);
        }
        .stChatMessage {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 1rem;
            margin-bottom: 1rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s ease-in-out;
        }
        .stChatMessage:hover {
            transform: translateY(-2px);
        }
        h1, h2, h3 {
            background: -webkit-linear-gradient(45deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            background: #38bdf8;
            color: #0f172a;
            margin-bottom: 10px;
        }
        </style>
    """, unsafe_allow_html=True)


load_css()


# --- Streamlit Session Initialization ---

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    logger.info(f"Initialized new Streamlit session: {st.session_state.session_id}")
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Session Management Sidebar ---
st.sidebar.title("History & Sessions 🗄️")
try:
    recent_sessions = requests.get(f"{API_URL}/sessions").json()
except requests.exceptions.ConnectionError:
    st.error("Cannot connect to API backend. Ensure FastAPI is running.")
    st.stop()

# Add option to start a new session
options = ["New Session"] + list(recent_sessions.keys())

# Find the index of the current session to set it as default in the selectbox
try:
    current_idx = options.index(st.session_state.session_id)
except ValueError:
    # If the current session ID isn't in the DB yet, it might just be the active "New Session"
    current_idx = 0

def format_session_label(sid):
    if sid == "New Session":
        return "✨ New Session"
    return recent_sessions.get(sid, sid)

def on_session_change():
    selected = st.session_state.session_selector
    if selected == "New Session":
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
    elif selected != st.session_state.session_id:
        st.session_state.session_id = selected
        # Hydrate messages from API
        msgs = requests.get(f"{API_URL}/sessions/{selected}/messages").json()
        st.session_state.messages = msgs

st.sidebar.selectbox(
    "Load Past Session", 
    options, 
    index=current_idx,
    format_func=format_session_label,
    key="session_selector",
    on_change=on_session_change
)
st.sidebar.divider()

# --- Graph Execution via API ---
def execute_graph(session_id: str, user_message: str, turn_number: int):
    """Invokes the LangGraph agent via the FastAPI backend."""
    response = requests.post(f"{API_URL}/chat", json={
        "session_id": session_id,
        "user_message": user_message,
        "turn_number": turn_number
    })
    response.raise_for_status()
    return response.json()


# --- Sidebar (Redis Projection Layer) ---
st.sidebar.title("Active Context ⚡")
st.sidebar.markdown(f"**Session ID:** `{st.session_state.session_id[:8]}...`")

active_state = requests.get(f"{API_URL}/sessions/{st.session_state.session_id}/state").json()
if active_state:
    st.sidebar.markdown("### Semantic State")
    op = active_state.get("operation")
    if op:
        st.sidebar.markdown(f"<span class='badge'>{op}</span>", unsafe_allow_html=True)

    st.sidebar.markdown(f"**Topic:** `{active_state.get('topic', 'None')}`")

    filters = active_state.get("filters", {})
    if filters:
        st.sidebar.markdown("**Active Filters:**")
        for k, v in filters.items():
            st.sidebar.markdown(f"- `{k}`: **{v}**")

    st.sidebar.markdown("### Execution")
    if active_state.get("last_error"):
        st.sidebar.error(active_state["last_error"])
    if active_state.get("last_sql"):
        with st.sidebar.expander("Last Generated SQL", expanded=True):
            st.code(active_state["last_sql"], language="sql")
    if active_state.get("last_row_count") is not None:
        st.sidebar.success(f"Matched {active_state['last_row_count']} rows")
else:
    st.sidebar.info("Start a conversation to populate active context.")


# --- Main Chat Interface ---
st.title(config.ui_page_title)
st.markdown(
    "Ask complex natural language questions about your database."
)

# Render History
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sql"):
            with st.expander("View Executed SQL"):
                st.code(msg["sql"], language="sql")
        if msg.get("data"):
            # Set fixed height to make the table compact and scrollable
            st.dataframe(msg["data"], height=250)
        if msg.get("error"):
            st.error(msg["error"])
        if msg.get("latency_ms") is not None and msg.get("tokens"):
            st.caption(f"⚡ *Executed in {msg['latency_ms'] / 1000:.2f}s | {msg['tokens']} tokens used*")

# Input handling
if prompt := st.chat_input("E.g., Show me the top 10 records sorted by date..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing intent and generating strict SQL..."):
            latency_ms = 0
            try:
                turn_number = len(st.session_state.messages) // 2
                start_time = time.monotonic()
                final_state = execute_graph(st.session_state.session_id, prompt, turn_number)
                latency_ms = int((time.monotonic() - start_time) * 1000)

                if final_state.get("pending_clarification"):
                    retries = final_state.get("retry_count", 0)
                    response_text = (
                        "Your request was a bit ambiguous. "
                        "Could you please clarify what you mean?"
                    )
                    response_text += f"\n\n*(Retries: {retries})*"
                    st.markdown(response_text)
                    st.session_state.messages.append(
                        {
                            "role": "assistant", 
                            "content": response_text,
                            "latency_ms": latency_ms,
                            "tokens": final_state.get("token_count", 0)
                        }
                    )

                elif final_state.get("operation") in ("REFUSE",):
                    retries = final_state.get("retry_count", 0)
                    response_text = (
                        "I'm sorry, but I can only answer questions strictly "
                        "related to the target database schemas."
                    )
                    response_text += f"\n\n*(Retries: {retries})*"
                    st.markdown(response_text)
                    st.session_state.messages.append(
                        {
                            "role": "assistant", 
                            "content": response_text,
                            "latency_ms": latency_ms,
                            "tokens": final_state.get("token_count", 0)
                        }
                    )

                elif final_state.get("last_error"):
                    err = final_state["last_error"]
                    retries = final_state.get("retry_count", 0)
                    response_text = f"I apologize, but I wasn't able to generate a valid query to answer your question after {retries} attempts. I've logged this failure for the engineering team."
                    st.error(response_text)
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": response_text,
                            "error": err,
                            "latency_ms": latency_ms,
                            "tokens": final_state.get("token_count", 0)
                        }
                    )

                else:
                    rows = final_state.get("last_row_count", 0)
                    sql = final_state.get("last_sql", "")
                    retries = final_state.get("retry_count", 0)
                    
                    response_text = f"Query successful. Found {rows} matching records. *(Retries: {retries})*"
                    if retries > 0:
                        response_text += f"\n\n*(Agent Self-Corrected: Recovered successfully after {retries} failed attempts)*"
                    
                    # Add dynamic disclaimers for transparency
                    if sql:
                        if "LIMIT 100" in sql.upper():
                            response_text += "\n\n*(Disclaimer: Results were automatically limited to 100 rows for performance.)*"
                        if "-273.0" in sql or "999.9" in sql:
                            response_text += "\n\n*(Disclaimer: Known invalid sensor readings were automatically excluded from this analysis.)*"
                            
                    st.markdown(response_text)

                    sample_data = final_state.get("last_result_sample", [])
                    if sample_data:
                        # Set fixed height to make the table compact and scrollable
                        st.dataframe(sample_data, height=250)
                    
                    if latency_ms is not None and final_state.get("token_count"):
                        st.caption(f"⚡ *Executed in {latency_ms / 1000:.2f}s | {final_state.get('token_count')} tokens used*")

                    if sql:
                        with st.expander("View Executed SQL"):
                            st.code(sql, language="sql")

                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": response_text,
                            "sql": sql,
                            "data": sample_data,
                            "latency_ms": latency_ms,
                            "tokens": final_state.get("token_count", 0)
                        }
                    )

                # Turn logging is now handled entirely on the FastAPI backend

            except Exception as e:
                import traceback
                logger.exception("Top-level exception caught in Streamlit chat execution.")
                
                # Show a graceful user-facing message
                st.error("Sorry, an internal system error occurred while processing your request. The engineering team has been automatically notified.")
