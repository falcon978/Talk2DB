# Talk2DB Custom Database Setup Guide

Talk2DB is built to be completely domain-agnostic. Out of the box, it comes with a sample dataset to demonstrate its capabilities. 

To use Talk2DB with your own PostgreSQL database, follow these steps to swap out the underlying schema and permissions.

## 1. Configure the Database Connection
Update the `DB_DSN_TARGET` environment variable in your `.env` file to point to your new database.
```bash
# .env
DB_DSN_TARGET=postgresql://readonly_user:password@localhost:5432/your_database
```

## 2. Update the LLM Schema Context
The LLM generates SQL dynamically by reading your schema. You must provide it with the structure of your database.
- Open `talk2db/prompts/schema.txt`.
- Delete the existing sample schema.
- Paste in your own database schema. This can be raw DDL (e.g., `CREATE TABLE...`) or a simplified text representation of your tables and columns. Be sure to include comments on any ENUMs or special constraints.

## 3. Update the Few-Shot Examples (Highly Recommended)
While the agent is zero-shot capable, providing relevant few-shot examples drastically reduces hallucination and improves complex joins.
- **Router Examples**: Open `talk2db/prompts/few_shot_router.txt` and replace the examples with semantic routing examples relevant to your data.
- **SQL Generation Examples**: Open `talk2db/prompts/few_shot_sql_gen.txt` and provide 3-5 complex SQL query examples matching your new schema.

## 4. Grant Database Permissions
For security, the LLM executes queries using a restricted `readonly_user`. If you are using your own existing PostgreSQL server, ensure you grant `SELECT` privileges to this user for the specific tables you want the LLM to access.

If you are using the included Docker Compose setup, update `db/init.sql`:
1. Remove the existing `CREATE TABLE` scripts.
2. Update the `GRANT SELECT` statement at the bottom to whitelist your new tables:
```sql
GRANT SELECT ON your_table_1, your_table_2 TO readonly_user;
```

## 5. Seed Data (Optional)
If you are bootstrapping a new database from CSVs:
- Place your new CSV files in the `db/data/` directory.
- Update `db/seed_csvs.py` to match your new table names and perform any necessary data type parsing (e.g., datetime conversions).
- Alternatively, you can remove `db/seed_csvs.py` entirely if you are connecting to a pre-populated database.

## 6. Update the Evaluation Harness (If Running Evals)
The evaluation framework in `eval/run_eval.py` is entirely domain-agnostic and relies on AST parsing to compare results. However, the evaluation **dataset** acts as your test suite.
- Open `eval/dataset.json`.
- Replace the existing examples with 10-20 "Golden Conversations" containing sample queries for your new database, the expected router operation (`NEW`, `REFINE`, `CLARIFY`, `REFUSE`), and the perfectly formatted `gold_sql` for execution comparison.
