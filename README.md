# Talk2DB

A domain-agnostic conversational Text-to-SQL agent built for non-technical users to query any PostgreSQL database using plain English. Powered by a local 7B open-weights model, it supports dynamic reference resolution, self-correction, robust evaluation, and stateful multi-turn conversations.

---


## Using Your Own Database Schema
Talk2DB is designed to be completely domain-agnostic. For a comprehensive guide on how to point it at your own database, define your schema, and set up permissions, please see the [SETUP.md](SETUP.md) guide.

## Setup & Run Instructions

### Hardware Requirements
- **OS**: macOS (M-series recommended), Linux, or Windows (WSL2).
- **RAM**: Minimum 16GB System RAM.
- **Compute**: Minimum 8GB VRAM (NVIDIA) or Apple Silicon Unified Memory. (The 7B quantized model requires ~4.7GB to run).

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- `pip` or `uv`

### Installation & Execution
```bash
# 1. Bring up the entire stack (DB, Model Runtime, Agent API, UI)
docker compose up -d

# 2. Wait for the model to pull (~3-5 minutes) and the agent to start.
# The UI will be available at http://localhost:8501
```
*(Note: Copy `.env.example` to `.env` to configure your environment variables before running).*

### Local Development (Optional)
If you prefer running the agent outside of Docker:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[api,ui,dev]"

# If testing locally, launch both the API and Streamlit UI in separate terminals
uvicorn api:app --reload
streamlit run app.py
```

### First-Run Model Download
- **Expected Download Size**: ~4.7 GB.
- **Expected Time**: ~3–5 minutes on a standard 100Mbps broadband connection.
*(Note: The model is automatically pulled via the `ollama-pull` initialization script in Docker Compose; no manual intervention is required).*

### Optional: LangSmith Tracing
Because the backend is built natively on LangGraph, full telemetry and execution tracing is supported out-of-the-box. To observe the cyclic graph execution and agentic reasoning in real-time, export your credentials before launching the API:
```bash
export LANGCHAIN_TRACING_V2="true"
export LANGCHAIN_API_KEY="your-api-key"
```

### Running the Evaluation Harness
To reproduce the baseline and final architecture evaluation reports locally:
```bash
# Run the Zero-Shot Baseline
python3 -m eval.run_baseline

# Run the Final Engineered System Evaluation
python3 -m eval.run_eval
```
All generated markdown reports with full failure traces and latency metrics are automatically saved to the `eval/reports/` directory.

---

## Model Card
- **Model Name**: Qwen2.5-Coder-7B
- **Parameter Count**: 7 Billion
- **Quantization**: 4-bit (Q4_K_M)
- **Runtime Environment**: Ollama (Local)
- **Hardware Executed On**: Apple M-Series (macOS) with 16GB Unified Memory

---

## Architecture & Multi-Turn Execution Lifecycle

Our system leverages a **State Machine (LangGraph)** to handle conversational routing and self-correction recursively.

1. **Input Reception**: The user types a query in the Streamlit UI. 
2. **Intent Routing**: The graph passes the new query and the bounded chat history to the Router LLM. Utilizing Structured Output Chain-of-Thought (CoT), the model classifies the operation (`NEW`, `REFINE`, `CLARIFY`, `REFUSE`) and extracts a clean JSON dictionary of active semantic filters (e.g., `{"district": "Solapur", "season": "kharif"}`).
3. **State Mutation**: The graph updates the active `AgentState`. If `NEW`, it wipes old filters. If `REFINE`, it cleanly merges the new filters into the persistent dictionary.
4. **SQL Generation**: The agent retrieves the current active filters, the database schema, and dynamically generates a raw PostgreSQL query via a deeply optimized Prompt Template injected with Few-Shot SQL examples.
5. **AST Guardrails**: The generated SQL is parsed via `sqlglot`. It explicitly blocks destructive nodes (`DROP`, `DELETE`, etc.), intercepts massive over-fetching via short wildcards (e.g., `ILIKE '%a%'`), and automatically injects missing `LIMIT` clauses.
6. **Isolated Execution**: The validated SQL is executed against a strictly read-only PostgreSQL pool (`target_pool`).
7. **Self-Correction Loop**: If the database throws a Syntax or Relation error, the graph traps the error and routes back to the SQL Generator, feeding it the exact Postgres error for up to 2 retry attempts.
8. **Asynchronous Logging & Rendering**: The results, generated SQL, retry count, token consumption, and exact query latency are logged to a persistent `chat_history` analytics table via a non-blocking background thread, while the UI instantly renders the dataframe and metrics for the user.

---



### Architecture Highlights
We engineered several advanced features that elevate this to a production-grade architecture:
- **Asynchronous FastAPI Backend**: Instead of blocking Streamlit, we decoupled the architecture into a high-performance async FastAPI backend (`api.py`) that manages non-blocking DB execution (`asyncpg`) and parallel state mutations.
- **Dual-Pool Database Isolation**: The LangGraph state checkpoints, execution telemetry (`chat_history`), and crash traces (`system_errors`) are logged securely via an Admin pool, while the LLM's dynamically generated queries are tightly sandboxed within a restricted `readonly_user` pool (explicitly whitelisted to only 7 target tables).
- **Session Resumption Time-Travel**: By leveraging LangGraph's native PostgreSQL checkpointer, users can switch between historical conversational sessions instantly in the UI. The semantic state (JSON filters) is perfectly hydrated from the database, allowing them to seamlessly resume a conversation from days ago.
- **Graceful UI Crash Handling**: Both backend and frontend exceptions are gracefully trapped. Instead of showing raw stack traces to the user, the UI displays polite fallback messages while asynchronously logging the exact stack trace to the persistent `system_errors` table for developer triage.


---

## Design Decisions & Trade-offs

### 1. Compensating for a Small (7B) Model
A 7B model prompted naively struggles with complex text-to-SQL logic and multi-turn context drift. 
- **Semantic Router**: We decoupled the raw conversation history from the SQL Generator. We use the model strictly as an *Information Extraction Router* on the first pass to build a rigidly structured JSON dictionary of active filters. The SQL Generator then only looks at this clean, extracted dictionary to write the SQL. This drastically reduces cognitive load and hallucination.
- **Structured Output Chain-of-Thought (CoT)**: By requiring the Pydantic schemas to define a `reasoning` string field *before* the actual output, we force the autoregressive LLM to "think out loud" before writing SQL. This mathematically increases generation accuracy.
- **KV Caching Optimization**: Massive, static text blocks like the Database Schema and System Instructions are strictly placed at the **top** of the prompts. Highly dynamic variables like `{history}` and `{user_query}` are placed at the absolute **bottom**. This guarantees that the LLM computes the Key-Value cache exactly once.

### 2. Framework Usage: LangGraph
We utilized **LangGraph** to orchestrate this directed cyclic graph.
- **What it does for us**: It natively handles the recursive `while` loop for our self-correction retries and automatically checkpoints our `AgentState` to PostgreSQL. This allows us to build a "Session Resumption" dropdown in the UI.

### 3. Conversation State Representation (Carry Forward vs. Discard)
- **What we carry forward**: The semantic state (Topic, Active JSON Filters, Group By clauses). This persists infinitely across the session.
- **What we discard**: The raw text conversation history. We strictly truncate the chat history to the last 4 turns (8 messages).

### 4. Guardrail Strategy & Database Isolation
We enforce security strictly **outside the model**. Prompting an LLM to "only write SELECT queries" is fundamentally unsafe. 
- We use `sqlglot` to parse the LLM's output into an Abstract Syntax Tree (AST), recursively walking the AST to explicitly block nested `Delete`/`Drop`/`Update` nodes even within subqueries. 
- We dynamically inject a `LIMIT 100` clause at the AST level to prevent unbounded queries.

### 5. Trade-off: Latency vs. Modular Architecture
By strictly enforcing the Single Responsibility Principle, processing a new query requires at least two sequential LLM inferences (Router classification → SQL generation), and a third if self-correction triggers. While this guarantees clean state management, it inherently introduces high latency when running a 7B model locally.
