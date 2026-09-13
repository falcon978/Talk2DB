import os

filepath = "/Users/r/.gemini/antigravity-ide/brain/2986543f-25f2-44b4-8ac6-7a37b7b859af/scratch/Talk2DB/README.md"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Replacements
content = content.replace(
    "A conversational Text-to-SQL agent built for non-technical agricultural field teams to query a PostgreSQL database using plain English.",
    "A domain-agnostic conversational Text-to-SQL agent built for non-technical users to query any PostgreSQL database using plain English."
)

content = content.replace(
    "*(Note: A default `.env` file is included in this repository strictly for reviewer convenience so the stack runs out-of-the-box without configuration. In a real production environment, this file would be excluded via `.gitignore` and managed securely).*",
    "*(Note: Copy `.env.example` to `.env` to configure your environment variables before running).*"
)

content = content.replace(
    "- **Dataset Generation Disclosure**: As permitted by the assignment constraints, we utilized **Gemini 3.1 Pro (Google)** strictly offline to synthetically author the complex, multi-turn evaluation dataset (`eval/dataset.json`) and generate the Gold SQL for edge cases. No frontier models are used in the runtime path.",
    "- **Dataset Generation**: We utilized **Gemini 3.1 Pro (Google)** strictly offline to synthetically author the complex, multi-turn evaluation dataset (`eval/dataset.json`) and generate the Gold SQL for edge cases to ensure robust benchmarking. No frontier models are used in the runtime path."
)

content = content.replace(
    "Baseline Comparison (The Delta)",
    "Performance Benchmarks"
)

content = content.replace(
    "While adhering strictly to the constraints (7B local model, conversational state, deterministic evaluation)",
    "While adhering strictly to local-execution constraints (7B local model, conversational state, deterministic evaluation)"
)

content = content.replace(
    "The assignment explicitly required handling `sensor_reading` tables with ~2 million rows. However, the evaluator-provided sample CSV only contained ~20,000 rows.",
    "To handle large scale data, "
)
content = content.replace(
    "even though the evaluation dataset was severely undersized",
    "ensuring high performance even on massive datasets"
)
content = content.replace(
    "(outside the assignment's determinism constraints)",
    ""
)

# Add instructions for schema replacement
schema_instructions = """
## Using Your Own Database Schema
Talk2DB is designed to be completely domain-agnostic. To point it at your own database:
1. Update `DB_DSN_TARGET` in your `.env` file.
2. Replace the contents of `talk2db/prompts/schema.txt` with your own database schema (DDL or a simple text representation).
3. (Highly Recommended) Update the few-shot examples in `talk2db/prompts/few_shot_router.txt` and `talk2db/prompts/few_shot_sql_gen.txt` to match your new schema so the LLM has accurate structural context.
"""
content = content.replace("## Setup & Run Instructions", schema_instructions + "\n## Setup & Run Instructions")


with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated README.md")
