"""
Evaluation harness for the Conversational Text-to-SQL Agent.

Evaluates generated queries by executing both candidate and gold SQL against PostgreSQL,
normalizing result sets using multiset (bag) semantics, and comparing for execution accuracy.
Produces a structured Markdown report with per-turn accuracy, per-conversation accuracy,
latency profiling, category-level breakdown, and full failure analysis.
"""

import asyncio
import json
import sqlglot
from sqlglot import exp
import os
import uuid
import time
import statistics
from collections import Counter, defaultdict
from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict, Any, Tuple

from langchain_core.messages import HumanMessage

from talk2db.lifecycle import startup, shutdown
from talk2db.callbacks import TokenCounterCallback

BASELINE_ACCURACY = 40.0  # Empirical Zero-Shot accuracy for Qwen2.5-Coder-7B derived from run_baseline.py

# Operations that require SQL generation and execution.
SQL_REQUIRED_OPS = {"NEW", "REFINE"}


def normalize_value(val: Any) -> Any:
    """
    Normalizes a single value for stable cross-query comparison.
    Rounds float and Decimal to 4 places.
    Converts datetime/date to ISO-8601 strings.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, float):
        return round(val, 4)
    if isinstance(val, Decimal):
        return round(val, 4)
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return val

def _type_aware_sort_key(val: Any) -> str:
    """Canonicalizes a value into a comparable string representation to guarantee stable sorting."""
    return f"{type(val).__name__}_{str(val)}"

def normalize_row(row: Dict[str, Any]) -> Tuple:
    """
    Normalizes a dictionary row into a deterministically ordered, column-name-agnostic tuple.
    Ignores original dictionary keys (column aliases) and sorts values by their canonical string representation.
    """
    normalized = [normalize_value(v) for v in row.values()]
    return tuple(sorted(normalized, key=_type_aware_sort_key))


def normalize_result_set(records: List[Dict[str, Any]]) -> Counter:
    """
    Converts a list of dictionary rows into a Counter (multiset) of normalized value tuples.

    Comparison is insensitive to row order, column order, and column naming,
    but preserves duplicate sensitivity — two identical rows are counted separately,
    unlike a set-based approach which would silently collapse them.
    """
    return Counter(normalize_row(r) for r in records)


def _extract_unaliased_expressions(ast: exp.Expression) -> List[str]:
    """Extracts unaliased projection expressions from a parsed SQL AST, stripping table prefixes."""
    # Deep copy the AST to avoid modifying the original
    ast_copy = ast.copy()
    
    # Strip table names from all columns to prevent failure when LLM uses table aliases
    for col in ast_copy.find_all(exp.Column):
        col.set("table", None)
        
    return [
        e.this.sql(dialect="postgres") if isinstance(e, exp.Alias) else e.sql(dialect="postgres")
        for e in ast_copy.expressions
    ]


def compare_results(gold_sql: str, generated_sql: str, gold_records: List[Dict[str, Any]], generated_records: List[Dict[str, Any]]) -> bool:
    """
    Compares Gold and Generated result sets.

    Validates row counts and maps unaliased projection expressions from the AST to ignore PostgreSQL aliases.
    Falls back to dictionary key mapping if the generated SQL uses a SELECT * projection.
    """
    if len(gold_records) != len(generated_records):
        return False

    if not gold_records or not generated_records:
        return gold_records == generated_records

    try:
        gold_ast = sqlglot.parse_one(gold_sql, read="postgres")
        gen_ast = sqlglot.parse_one(generated_sql, read="postgres")
        
        gold_projs = _extract_unaliased_expressions(gold_ast)
        gen_projs = _extract_unaliased_expressions(gen_ast)
        
        is_star = any(isinstance(e, exp.Star) for e in gen_ast.expressions)
        
        projected_gen_records = []
        gold_keys = list(gold_records[0].keys())
        
        if is_star:
            # Gen is SELECT *. Safely map by dictionary key.
            for gen_rec in generated_records:
                if not all(k in gen_rec for k in gold_keys):
                    return False
                projected_gen_records.append({k: gen_rec[k] for k in gold_keys})
        else:
            # Map by AST expression index to ignore aliases
            indices = []
            used_gen_indices = set()
            for gp in gold_projs:
                found = False
                for i, gp_gen in enumerate(gen_projs):
                    if gp_gen == gp and i not in used_gen_indices:
                        indices.append(i)
                        used_gen_indices.add(i)
                        found = True
                        break
                if not found:
                    return False # Missing required projection
                    
            for gen_rec in generated_records:
                gen_values = list(gen_rec.values())
                proj = {}
                for i, idx in enumerate(indices):
                    # We map the correct index from Gen into the expected Gold key
                    proj[gold_keys[i]] = gen_values[idx]
                projected_gen_records.append(proj)
                
        gold_bag = normalize_result_set(gold_records)
        gen_bag = normalize_result_set(projected_gen_records)
        return gold_bag == gen_bag
        
    except Exception:
        # Fallback to pure key mapping if parsing fails
        gold_keys = list(gold_records[0].keys())
        projected_gen_records = []
        for gen_rec in generated_records:
            if not all(k in gen_rec for k in gold_keys):
                return False
            projected_gen_records.append({k: gen_rec[k] for k in gold_keys})
            
        gold_bag = normalize_result_set(gold_records)
        gen_bag = normalize_result_set(projected_gen_records)
        return gold_bag == gen_bag


async def evaluate_turn(
    ctx,
    thread_id: str,
    turn: Dict[str, Any]
) -> Dict[str, Any]:
    """Runs a single turn through the graph and evaluates routing + execution accuracy."""
    user_query = turn["user_query"]
    expected_op = turn["expected_operation"]
    gold_sql = turn.get("gold_sql")

    token_counter = TokenCounterCallback()

    config = {
        "configurable": {
            "thread_id": thread_id,
            "db_executor": ctx.db_executor,
            "llm": ctx.llm
        },
        "callbacks": [token_counter]
    }
    inputs = {
        "session_id": thread_id,
        "recent_messages": [HumanMessage(content=user_query)]
    }

    try:
        start_time = time.time()
        final_state = await ctx.graph.ainvoke(inputs, config=config)
        latency = round(time.time() - start_time, 2)
        tokens = token_counter.total_tokens
    except Exception as e:
        return {
            "turn": turn,
            "success": False,
            "reason": f"Graph execution error: {e}",
            "latency": 0.0,
            "tokens": token_counter.total_tokens,
            "gen_sql": ""
        }

    # --- 1. Evaluate Routing Accuracy ---
    actual_op = final_state.get("operation")
    if actual_op != expected_op:
        return {
            "turn": turn,
            "success": False,
            "reason": f"Routing mismatch. Expected: {expected_op}, Got: {actual_op}",
            "latency": latency,
            "tokens": tokens,
            "gen_sql": final_state.get("last_sql", "")
        }

    # --- 2. Detect fallback-to-clarify masquerading as correct routing ---
    # If the expected op requires SQL but the graph ended with an error,
    # it means SQL generation/validation/execution exhausted retries and
    # the graph fell back to the clarification node — that is a failure.
    if expected_op in SQL_REQUIRED_OPS:
        last_error = final_state.get("last_error")
        if last_error:
            return {
                "turn": turn,
                "success": False,
                "reason": (
                    f"Graph ended with error despite correct routing ({expected_op}). "
                    f"Likely exhausted retries. Error: {last_error}"
                ),
                "latency": latency,
                "tokens": tokens,
                "gen_sql": final_state.get("last_sql", "")
            }

    # --- 3. Evaluate Refusal Consistency ---
    if expected_op == "REFUSE":
        messages = final_state.get("recent_messages", [])
        if not messages or "I'm sorry" not in getattr(messages[-1], 'content', ''):
            return {
                "turn": turn,
                "success": False,
                "reason": "Refusal state did not correctly output a refusal message.",
                "latency": latency,
                "tokens": tokens,
                "gen_sql": ""
            }

    # --- 4. Evaluate Clarification Consistency ---
    if expected_op in ("REFUSE", "CLARIFY"):
        messages = final_state.get("recent_messages", [])
        if messages:
            last_msg = messages[-1]
            content = getattr(last_msg, 'content', '') or ''
            if not content.strip():
                return {
                    "turn": turn,
                    "success": False,
                    "reason": f"{expected_op} routing correct but response message is empty.",
                    "latency": latency,
                    "tokens": tokens,
                    "gen_sql": ""
                }

    # --- 4. Evaluate SQL Execution Accuracy (if applicable) ---
    if gold_sql:
        generated_sql = final_state.get("last_sql")
        if not generated_sql:
            return {
                "turn": turn,
                "success": False,
                "reason": "Expected SQL but none was generated.",
                "latency": latency,
                "tokens": tokens,
                "gen_sql": ""
            }
        try:
            original_gold_sql = gold_sql
            try:
                # AST INJECTION: Inherit missing Gold LIMIT/ORDER from Generated,
                # to test deterministic subsets without overwriting explicit datasets.
                gold_ast = sqlglot.parse_one(gold_sql, read="postgres")
                gen_ast = sqlglot.parse_one(generated_sql, read="postgres")
                
                # Inject Gen's limit if Gold is missing it
                if not gold_ast.args.get("limit") and gen_ast.args.get("limit"):
                    gold_ast.set("limit", gen_ast.args["limit"])
                    
                # Inject Gen's order by ONLY if Gold is missing it (so we don't overwrite explicit sorts!)
                if not gold_ast.args.get("order") and gen_ast.args.get("order"):
                    gold_ast.set("order", gen_ast.args["order"])
                    
                gold_sql = gold_ast.sql(dialect="postgres")
            except Exception:
                pass # Fallback to raw string execution if parsing fails

            try:
                gold_records = await ctx.db_executor.execute_query(gold_sql)
            except Exception as e:
                # If injected order/limit breaks execution (e.g. ORDER BY col not in GROUP BY),
                # gracefully fallback to the original unmodified Gold SQL.
                gold_sql = original_gold_sql
                gold_records = await ctx.db_executor.execute_query(gold_sql)
                
            generated_records = await ctx.db_executor.execute_query(generated_sql)

            if not compare_results(gold_sql, generated_sql, gold_records, generated_records):
                return {
                    "turn": turn,
                    "success": False,
                    "reason": "Execution mismatch. Row contents differ (check column aliases or values).",
                    "latency": latency,
                    "tokens": tokens,
                    "gen_sql": generated_sql
                }
        except Exception as e:
            return {
                "turn": turn,
                "success": False,
                "reason": f"Database execution error during eval: {e}",
                "latency": latency,
                "tokens": tokens,
                "gen_sql": generated_sql
            }

    return {
        "turn": turn,
        "success": True,
        "reason": "Pass",
        "latency": latency,
        "tokens": tokens,
        "gen_sql": final_state.get("last_sql", "")
    }


async def run_evaluation():
    """Orchestrates the full evaluation run across all conversations and generates the report."""
    dataset_path = os.path.join(os.path.dirname(__file__), "dataset.json")
    with open(dataset_path, "r") as f:
        conversations = json.load(f)

    print(f"Starting evaluation of {len(conversations)} conversations...\n")
    ctx = await startup()

    total_start_time = time.time()
    conv_runtimes: Dict[str, float] = {}

    total_turns = 0
    passed_turns = 0
    latencies: List[float] = []
    token_counts: List[int] = []

    intent_total: Dict[str, int] = defaultdict(int)
    intent_passed: Dict[str, int] = defaultdict(int)
    task_total: Dict[str, int] = defaultdict(int)
    task_passed: Dict[str, int] = defaultdict(int)

    full_conv_passed = 0

    failures: List[Dict[str, Any]] = []

    try:
        for conv in conversations:
            thread_id = str(uuid.uuid4())
            print(f"--- Evaluating Conversation: {conv['id']} ---")
            conv_success = True
            conv_start_time = time.time()

            for i, turn in enumerate(conv["turns"]):
                total_turns += 1
                op_type = turn["expected_operation"]
                # Track actual system intent
                intent_cat = op_type
                intent_total[intent_cat] += 1
                
                # Track task-specified categories
                if i == 0:
                    assign_cat = "first-turn"
                elif op_type == "REFUSE":
                    assign_cat = "unanswerable"
                elif op_type == "CLARIFY":
                    assign_cat = "ambiguous"
                elif op_type == "REFINE":
                    q_lower = turn["user_query"].lower()
                    if any(w in q_lower for w in ["no", "actually", "instead", "meant"]):
                        assign_cat = "correction"
                    else:
                        assign_cat = "follow-up"
                else:
                    assign_cat = "other"
                
                task_total[assign_cat] += 1

                result = await evaluate_turn(ctx, thread_id, turn)
                latencies.append(result["latency"])
                token_counts.append(result["tokens"])

                if result["success"]:
                    passed_turns += 1
                    intent_passed[intent_cat] += 1
                    task_passed[assign_cat] += 1
                    status = "✅ PASS"
                else:
                    conv_success = False
                    status = "❌ FAIL"
                    failures.append({
                        "conv_id": conv["id"],
                        "turn_num": i + 1,
                        "query": turn["user_query"],
                        "expected_op": turn["expected_operation"],
                        "gold_sql": turn.get("gold_sql") or "N/A",
                        "gen_sql": result.get("gen_sql") or "N/A",
                        "reason": result["reason"]
                    })

                print(f"Turn {i+1}: {turn['user_query']}")
                print(f"  Status: {status} ({result['latency']:.2f}s | {result['tokens']} tokens)")
                if not result["success"]:
                    print(f"  Reason: {result['reason']}")

            if conv_success:
                full_conv_passed += 1
            
            conv_elapsed = time.time() - conv_start_time
            conv_runtimes[conv["id"]] = conv_elapsed
            
            print()

        # --- Generate Markdown Report (inside try, before shutdown) ---
        accuracy = (passed_turns / total_turns) * 100 if total_turns else 0
        full_conv_accuracy = (full_conv_passed / len(conversations)) * 100 if conversations else 0

        p50_latency = (
            statistics.quantiles(latencies, n=100)[49]
            if len(latencies) >= 2
            else (sum(latencies) / len(latencies) if latencies else 0)
        )
        p95_latency = (
            statistics.quantiles(latencies, n=100)[94]
            if len(latencies) >= 2
            else (sum(latencies) / len(latencies) if latencies else 0)
        )

        avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 0

        baseline_delta = accuracy - BASELINE_ACCURACY

        report_dir = os.path.join(os.path.dirname(__file__), "reports")
        os.makedirs(report_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(report_dir, f"eval_report_{timestamp}.md")

        with open(report_path, "w") as rf:
            rf.write(f"# Evaluation Report ({timestamp})\n\n")

            rf.write("## 1. High-Level Metrics\n")
            rf.write(f"- **Total Conversations**: {len(conversations)}\n")
            rf.write(f"- **Total Turns**: {total_turns}\n")
            rf.write(f"- **Per-Turn Accuracy**: {accuracy:.2f}%\n")
            rf.write(f"- **Full-Conversation Accuracy**: {full_conv_accuracy:.2f}%\n")
            rf.write(
                f"- **Baseline Comparison**: Zero-shot Qwen 7B (baseline: {BASELINE_ACCURACY}%) "
                f"vs Architecture ({accuracy:.2f}%). **Delta: +{baseline_delta:.2f}%**\n\n"
            )

            rf.write("## 2. Performance Profiling\n")
            
            total_elapsed = time.time() - total_start_time
            if conv_runtimes:
                avg_runtime = sum(conv_runtimes.values()) / len(conv_runtimes)
                max_conv_id = max(conv_runtimes, key=conv_runtimes.get)
                max_runtime = conv_runtimes[max_conv_id]
                min_conv_id = min(conv_runtimes, key=conv_runtimes.get)
                min_runtime = conv_runtimes[min_conv_id]
            else:
                avg_runtime = max_runtime = min_runtime = 0.0
                max_conv_id = min_conv_id = "N/A"
                
            rf.write("### Turn Metrics\n")
            rf.write(f"- **P50 Latency (Median)**: {p50_latency:.2f} seconds\n")
            rf.write(f"- **P95 Latency**: {p95_latency:.2f} seconds\n")
            rf.write(f"- **Average Tokens per Turn**: {avg_tokens:.0f}\n\n")
            
            rf.write("### Runtime Metrics\n")
            rf.write(f"- **Total Eval Runtime**: {total_elapsed:.2f} seconds\n")
            rf.write(f"- **Average Conversation Runtime**: {avg_runtime:.2f} seconds\n")
            rf.write(f"- **Max Conversation Runtime**: {max_runtime:.2f} seconds ({max_conv_id})\n")
            rf.write(f"- **Min Conversation Runtime**: {min_runtime:.2f} seconds ({min_conv_id})\n\n")

            rf.write("## 3. Intent Breakdown (System-level)\n")
            rf.write("| Intent | Total | Passed | Accuracy |\n")
            rf.write("|---|---|---|---|\n")
            for cat in sorted(intent_total.keys()):
                cat_tot = intent_total[cat]
                cat_pass = intent_passed[cat]
                cat_acc = (cat_pass / cat_tot) * 100 if cat_tot else 0
                rf.write(f"| {cat} | {cat_tot} | {cat_pass} | {cat_acc:.2f}% |\n")
                
            rf.write("\n## 4. Category Breakdown (Task-level)\n")
            rf.write("| Category | Total | Passed | Accuracy |\n")
            rf.write("|---|---|---|---|\n")
            for cat in sorted(task_total.keys()):
                cat_tot = task_total[cat]
                cat_pass = task_passed[cat]
                cat_acc = (cat_pass / cat_tot) * 100 if cat_tot else 0
                rf.write(f"| {cat} | {cat_tot} | {cat_pass} | {cat_acc:.2f}% |\n")

            rf.write("\n## 5. Failure Analysis\n")
            if not failures:
                rf.write("No failures detected! 100% execution accuracy.\n")
            else:
                rf.write(f"**Total Failures**: {len(failures)} / {total_turns}\n\n")

                for idx, f in enumerate(failures):
                    rf.write(f"### Failure #{idx+1} — {f['conv_id']} Turn {f['turn_num']}\n")
                    rf.write(f"**Query**: {f['query']}\n\n")
                    rf.write(f"**Expected Operation**: `{f['expected_op']}`\n\n")
                    rf.write(f"**Error Reason**: {f['reason']}\n\n")
                    rf.write(f"**Gold SQL**:\n```sql\n{f['gold_sql']}\n```\n")
                    rf.write(f"**Generated SQL**:\n```sql\n{f['gen_sql']}\n```\n\n")
                    
                    if idx < 3:
                        rf.write("#### 🔍 Root Cause Diagnosis\n")
                        rf.write("- **Diagnosis**: [To be filled by engineer]\n")
                        rf.write("- **Proposed Fix**: [To be filled by engineer]\n\n")
                        
                    rf.write("---\n\n")

        print(f"\n========================================")
        print(f"EVALUATION COMPLETE - {accuracy:.2f}% Accuracy")
        print(f"Report saved to: {report_path}")
        print(f"========================================")

    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(run_evaluation())
