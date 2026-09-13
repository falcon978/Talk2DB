import asyncio
import json
import os
import time
import re
from typing import List, Dict, Any
from datetime import datetime

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage

from talk2db.lifecycle import startup, shutdown
from eval.run_eval import compare_results

SCHEMA = """
CREATE TABLE farmer (id UUID, name TEXT, district TEXT, state TEXT, registered_on DATE, is_active BOOLEAN);
CREATE TABLE plot (id UUID, farmer_id UUID, area_hectares NUMERIC, soil_type TEXT, district TEXT, irrigation_type TEXT);
CREATE TABLE crop_cycle (id UUID, plot_id UUID, crop TEXT, season TEXT, sown_date DATE, harvest_date DATE, expected_yield NUMERIC, actual_yield NUMERIC, status TEXT);
CREATE TABLE advisory (id UUID, plot_id UUID, issued_at TIMESTAMP, category TEXT, severity TEXT, acknowledged_at TIMESTAMP);
CREATE TABLE sensor_reading (id UUID, plot_id UUID, reading_type TEXT, value NUMERIC, recorded_at TIMESTAMP);
CREATE TABLE field_agent (id UUID, name TEXT, district TEXT, joined_on DATE);
CREATE TABLE field_visit (id UUID, plot_id UUID, agent_id UUID, visited_at TIMESTAMP, outcome TEXT, notes TEXT);
"""

def extract_sql(text: str) -> str:
    # Try to extract from markdown code blocks
    pattern = re.compile(r"```(?:sql)?\n(.*?)```", re.IGNORECASE | re.DOTALL)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()

async def run_baseline():
    dataset_path = os.path.join(os.path.dirname(__file__), "dataset.json")
    with open(dataset_path, "r") as f:
        conversations = json.load(f)

    print(f"Starting Zero-Shot Baseline evaluation...\n")
    ctx = await startup()
    
    llm = ChatOllama(
        model=os.getenv("LLM_MODEL_NAME", "qwen2.5-coder:7b-instruct-q4_K_M"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=0.0
    )

    total_sql_turns = 0
    passed_sql_turns = 0
    latencies = []
    failures = []

    try:
        for conv in conversations:
            print(f"--- Evaluating Conversation: {conv['id']} ---")
            
            # For zero-shot, we might not maintain conversational state perfectly in a simple baseline,
            # but we can provide the raw chat history as context to be fair.
            history = []
            
            for i, turn in enumerate(conv["turns"]):
                user_query = turn["user_query"]
                expected_op = turn["expected_operation"]
                gold_sql = turn.get("gold_sql")
                
                history.append(HumanMessage(content=user_query))
                
                if expected_op not in ["NEW", "REFINE"] or not gold_sql:
                    # Skip non-SQL turns for the zero-shot baseline, as a pure text-to-SQL model
                    # without an agent architecture doesn't classify intent or refuse inherently well.
                    print(f"Turn {i+1}: Skipped (Operation: {expected_op})")
                    # We need to simulate the assistant response so history isn't just human messages
                    history.append(HumanMessage(content="Skipped non-SQL turn.", role="assistant"))
                    continue
                    
                total_sql_turns += 1
                
                prompt = f"""You are a PostgreSQL expert. Write a query to answer the following question.
Schema:
{SCHEMA}

Question: {user_query}

Return ONLY the valid SQL query inside a markdown code block, and nothing else.
"""
                # Replace the last message with our full prompt for this baseline
                messages_to_send = history[:-1] + [HumanMessage(content=prompt)]
                
                start_time = time.time()
                try:
                    response = await llm.ainvoke(messages_to_send)
                    raw_text = response.content
                    gen_sql = extract_sql(raw_text)
                except Exception as e:
                    raw_text = ""
                    gen_sql = ""
                    print(f"LLM Error: {e}")
                    
                latency = time.time() - start_time
                latencies.append(latency)
                
                # Append the raw text to history for the next turn
                history.append(HumanMessage(content=raw_text, role="assistant"))
                
                success = False
                reason = "Execution mismatch or failure"
                
                if gen_sql:
                    try:
                        gold_records = await ctx.db_executor.execute_query(gold_sql)
                        generated_records = await ctx.db_executor.execute_query(gen_sql)
                        
                        if compare_results(gold_sql, gen_sql, gold_records, generated_records):
                            success = True
                            passed_sql_turns += 1
                            reason = "Pass"
                        else:
                            reason = "Execution mismatch (results differ)"
                    except Exception as e:
                        reason = f"DB Execution Error: {e}"
                else:
                    reason = "No SQL generated"

                status = "✅ PASS" if success else "❌ FAIL"
                print(f"Turn {i+1}: {user_query}")
                print(f"  Status: {status} ({latency:.2f}s)")
                if not success:
                    print(f"  Reason: {reason}")
                    failures.append({
                        "conv_id": conv["id"],
                        "turn_num": i + 1,
                        "query": user_query,
                        "gold_sql": gold_sql,
                        "gen_sql": gen_sql,
                        "reason": reason
                    })
                    
            print()

        accuracy = (passed_sql_turns / total_sql_turns) * 100 if total_sql_turns else 0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        report_dir = os.path.join(os.path.dirname(__file__), "reports")
        os.makedirs(report_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(report_dir, f"baseline_report_{timestamp}.md")

        with open(report_path, "w") as rf:
            rf.write(f"# Zero-Shot Baseline Report ({timestamp})\n\n")
            rf.write("## High-Level Metrics\n")
            rf.write(f"- **Total SQL Turns Evaluated**: {total_sql_turns}\n")
            rf.write(f"- **Passed Turns**: {passed_sql_turns}\n")
            rf.write(f"- **Baseline Accuracy**: {accuracy:.2f}%\n")
            rf.write(f"- **Average Latency**: {avg_latency:.2f}s\n\n")
            
            rf.write("## Failures\n")
            for f in failures:
                rf.write(f"### {f['conv_id']} Turn {f['turn_num']}\n")
                rf.write(f"**Query**: {f['query']}\n")
                rf.write(f"**Reason**: {f['reason']}\n")
                rf.write(f"**Generated SQL**:\n```sql\n{f['gen_sql']}\n```\n")
                rf.write(f"**Gold SQL**:\n```sql\n{f['gold_sql']}\n```\n\n")

        print(f"========================================")
        print(f"BASELINE EVALUATION COMPLETE - {accuracy:.2f}% Accuracy")
        print(f"Report saved to: {report_path}")
        print(f"========================================")

    finally:
        await shutdown()

if __name__ == "__main__":
    asyncio.run(run_baseline())
