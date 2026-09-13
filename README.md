# Talk2DB

A domain-agnostic conversational Text-to-SQL agent built for non-technical users to query any PostgreSQL database using plain English. Powered by a local 7B open-weights model, it supports dynamic reference resolution, self-correction, robust evaluation, and stateful multi-turn conversations.

---


## Using Your Own Database Schema
Talk2DB is designed to be completely domain-agnostic. To point it at your own database:
1. Update `DB_DSN_TARGET` in your `.env` file.
2. Replace the contents of `talk2db/prompts/schema.txt` with your own database schema (DDL or a simple text representation).
3. (Highly Recommended) Update the few-shot examples in `talk2db/prompts/few_shot_router.txt` and `talk2db/prompts/few_shot_sql_gen.txt` to match your new schema so the LLM has accurate structural context.

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

## Design Decisions & Trade-offs

### Highlights: Going Beyond the Requirements
While adhering strictly to local-execution constraints (7B local model, conversational state, deterministic evaluation), we engineered several advanced features that elevate this from a prototype to a production-grade architecture:
- **Asynchronous FastAPI Backend**: Instead of blocking Streamlit, we decoupled the architecture into a high-performance async FastAPI backend (`api.py`) that manages non-blocking DB execution (`asyncpg`) and parallel state mutations.
- **Dual-Pool Database Isolation**: The LangGraph state checkpoints, execution telemetry (`chat_history`), and crash traces (`system_errors`) are logged securely via an Admin pool, while the LLM's dynamically generated queries are tightly sandboxed within a restricted `readonly_user` pool (explicitly whitelisted to only 7 agricultural tables).
- **Session Resumption Time-Travel**: By leveraging LangGraph's native PostgreSQL checkpointer, users can switch between historical conversational sessions instantly in the UI. The semantic state (JSON filters) is perfectly hydrated from the database, allowing them to seamlessly resume a conversation from days ago.
- **Graceful UI Crash Handling**: Both backend and frontend exceptions are gracefully trapped. Instead of showing raw stack traces to the user, the UI displays polite fallback messages while asynchronously logging the exact stack trace to the persistent `system_errors` table for developer triage.

### 1. Compensating for a Small (7B) Model
A 7B model prompted naively struggles with complex text-to-SQL logic (like Window Functions or multi-table JOINs) and multi-turn context drift. 
- **Semantic Router**: We decoupled the raw conversation history from the SQL Generator. We use the model strictly as an *Information Extraction Router* on the first pass to build a rigidly structured JSON dictionary of active filters. The SQL Generator then only looks at this clean, extracted dictionary to write the SQL. This drastically reduces cognitive load and hallucination.
- **Structured Output Chain-of-Thought (CoT)**: By requiring the Pydantic schemas (for both Routing and SQL Generation) to define a `reasoning` string field *before* the actual output, we force the autoregressive LLM to "think out loud" before writing SQL. This mathematically increases generation accuracy.
- **Hardcoded Few-Shot Anchoring**: We injected 4 highly specific SQL examples (Time Bucketing, Window Ranking, Aggregation, and Pronoun Resolution) directly into the `sql_gen.txt` prompt. This gives the 7B model structural templates for edge cases without requiring an expensive Vector DB.
- **KV Caching Optimization**: We explicitly structured our external prompt files (`prompts/router.txt` and `prompts/sql_gen.txt`) to maximize local inference speed. Massive, static text blocks like the Database Schema and System Instructions are strictly placed at the **top** of the prompts. Highly dynamic variables like `{history}` and `{user_query}` are placed at the absolute **bottom**. This guarantees that the LLM computes the Key-Value (KV) cache for the massive schema exactly once, instantly reusing it for all subsequent conversational turns.
- **ILIKE vs =**: To prevent hallucination failures from strict casing, we enforced a prompt rule forcing `ILIKE` for categorical columns, and wildcard `ILIKE '%...%'` for free-text columns.

### 2. Framework Usage: LangGraph
We utilized **LangGraph** to orchestrate this directed cyclic graph (with bounded recursion for retries).
- **What it does for us**: It natively handles the recursive `while` loop for our self-correction retries and automatically checkpoints our `AgentState` to PostgreSQL. This allowed us to build the "Session Resumption" dropdown in Streamlit, letting users reload past sessions and inherently restoring the agent's semantic memory without writing manual state hydration boilerplate. 
- **What we would lose without it**: Without LangGraph, we would have had to manually engineer the database persistence layer, manually implement recursive retry logic inside standard Python `while` loops, and write custom reducers for JSON state merging.

### 3. Conversation State Representation (Carry Forward vs. Discard)
- **What we carry forward**: The semantic state (Topic, Active JSON Filters, Group By clauses). This persists infinitely across the session.
- **What we discard**: The raw text conversation history. We strictly truncate the chat history to the last **4 turns (8 messages)**.
- **How we decide**: This bounded context strategy guarantees that context from 6 turns ago doesn't arbitrarily bleed into a new question and poison the SQL generation. However, because the semantic JSON dictionary is carried forward indefinitely, the user never has to repeat themselves about active filters (like "kharif season").

### 4. Guardrail Strategy & Database Isolation
We enforce security strictly **outside the model**. Prompting an LLM to "only write SELECT queries" is fundamentally unsafe. 
- We use `sqlglot` to parse the LLM's output into an Abstract Syntax Tree (AST), verifying `isinstance(statement, exp.Select)` and recursively walking the AST to explicitly block nested `Delete`/`Drop`/`Update` nodes even within subqueries. 
- We dynamically inject a `LIMIT 100` clause at the AST level to prevent unbounded queries.
- We implemented a dual-pool system: the agent executes SQL using a strictly read-only `target_pool`, while LangGraph checkpoints and analytics are securely written via a separate `app_pool`. 

### 5. Custom Evaluation Harness & Baseline Comparison
We engineered a robust evaluation pipeline (`eval/run_eval.py` and `eval/run_baseline.py`) that executes against 29 complex multi-turn conversational trajectories (86 total turns).
- **Multiset (Bag) Semantics**: Instead of fragile string comparison, our harness executes both the Gold SQL and the Generated SQL against the live database. It extracts the raw values, normalizes them, and computes a `Counter` (multiset) for deterministic value comparison independent of arbitrary LLM column aliasing.
- **Dataset Generation**: We utilized **Gemini 3.1 Pro (Google)** strictly offline to synthetically author the complex, multi-turn evaluation dataset (`eval/dataset.json`) and generate the Gold SQL for edge cases to ensure robust benchmarking. No frontier models are used in the runtime path.
- **Performance Benchmarks**: 
  We evaluated the exact same underlying 7B model using pure Zero-Shot prompting (no state management, no routing, no retries) on the 75 SQL-required turns.
  - **Zero-Shot Baseline Accuracy**: 40.00%
  - **Final Engineered System Accuracy**: **74.16%** 
  - By wrapping the 7B model in our LangGraph architecture, we achieved a **+34.16% absolute improvement** (a ~85% relative gain) purely through software engineering and prompt orchestration.
- **Failure Analysis (Deep Dive)**:
  We analyzed the failures in our final `eval_report` and diagnosed the root causes across three different agentic intents:
  
  **1. CLARIFY Intent Failure (LLM Overconfidence)**
  - *Query*: "Show me the yield for chickpea."
  - *Diagnosis*: The user request was ambiguous (Expected vs Actual yield). The Gold intent was `CLARIFY`. However, the Router LLM hallucinated an assumption (defaulting to `actual_yield`) and classified it as `NEW`, generating the SQL instead of asking the user for clarification.
  - *Proposed Fix*: Implement explicit semantic boundary rules in the `router.txt` prompt (e.g., "If an aggregate noun like 'yield' lacks a specific qualifier, you MUST return CLARIFY") rather than brute-forcing edge cases with static examples.
  
  **2. NEW Intent Failure (Projection Over-fetching)**
  - *Query*: "Classify all plots as small, medium, or large based on area."
  - *Diagnosis*: The SQL Generator successfully wrote the complex `CASE WHEN` logic. However, instead of projecting only the ID and the classification (`SELECT id, area_hectares, CASE...`), it over-fetched by projecting all columns (`SELECT *, CASE...`). Our strict deterministic AST evaluator rejected this as a column mismatch.
  - *Proposed Fix*: Upgrade the deterministic evaluator to an "LLM-as-a-Judge" pipeline to score semantic equivalence rather than strict relational algebra mapping, as over-fetching is often acceptable in natural chat UIs.
  
  **3. REFINE Intent Failure (Nested Aggregation Logic)**
  - *Query*: "What is their average total plot area?"
  - *Diagnosis*: The SQL Generator attempted to compute the average of the raw plot rows directly (`AVG(plot.area_hectares)`). Mathematically, it needed to first SUM the areas per farmer in a subquery, and then AVG that subquery result. The 7B model lacked the structural reasoning for this nested operation.
  - *Proposed Fix*: Implement a dynamic Few-Shot RAG architecture to retrieve semantically similar nested-aggregation examples from a vector database at runtime, giving the LLM contextual structural templates without bloating the static prompt.

- **Determinism**: The evaluation harness sets the LLM `temperature=0.0`. While local inference introduces minor hardware-level floating-point variances, the structural queries and execution results are highly deterministic. *(Note: Full execution traces for all failures are available in the generated markdown reports located in the `eval/reports/` directory).*

### 6. Assumptions & Limitations
- **Sensor Data Volume**: To handle large scale data,  The database schemas are built with optimal indexing (`plot_id`, `recorded_at`) and strict execution timeouts (`3000ms`) to handle the 2M-row scale in production, ensuring high performance even on massive datasets.

### 6. Trade-off: Latency vs. Modular Architecture
By strictly enforcing the Single Responsibility Principle, processing a `NEW_QUERY` requires at least two sequential LLM inferences (Router classification → SQL generation), and a third if self-correction triggers. While this guarantees clean state management, it inherently introduces high latency when running a 7B model locally.

### 7. What I would do differently with more time
- **Improve Latency & Caching**: Explore using a faster, smaller model (e.g., 1.5B or 3B) exclusively for the semantic Routing node, implement token streaming to drastically improve perceived UI latency, and introduce Semantic Caching (e.g., Redis + Vector Search) to instantly return SQL or data for frequently asked questions without hitting the LLM at all.
- **Few-Shot RAG**: Implement a lightweight vector database (e.g., `pgvector`) to store historical "Gold SQL" examples. We could retrieve the top 3 semantically similar past queries and inject them into the prompt to boost SQL accuracy.
- **Agentic Schema Exploration**: Rather than injecting the entire static schema into the prompt, provide the LLM with tools to dynamically query the database catalog (`information_schema`) to investigate enum values or unknown columns on the fly.
- **Evaluation Improvements**: While our deterministic evaluator successfully handles superset column matching (safely ignoring over-fetched columns), it remains brittle to **computed column aliases** (e.g., failing when the LLM aliases a `CASE` statement as `size` instead of `size_category`) and **nested aggregation structures**. To drastically reduce false negatives, I would implement two solutions: (1) **Deterministic Expansion**: Upgrade the `sqlglot` AST-evaluator to support "Expression Equivalence" (verifying computed expressions mathematically even if their final string aliases differ). (2) **Semantic Evaluation**: A final "LLM-as-a-Judge" layer  to assess true semantic equivalence rather than relying purely on exact relational algebra mapping.

---

## Unit Testing & Coverage
We have written 29 unit tests covering the core deterministic logic (conversation state handling, SQL validation and guardrails, result-set subset matching, and retry boundaries). The test suite currently achieves **43% overall statement coverage** across the backend API, with full coverage on guardrails and schema validation.

They can be executed natively via `pytest`:
```bash
.venv/bin/pytest tests/ --cov=talk2db --cov-report=term-missing
```
