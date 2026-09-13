"""
Evaluation module for the Talk2DB.

This module contains the offline evaluation harness.

## Dataset Format (`dataset.json`)
The evaluation dataset is a JSON array of conversation objects. Each conversation
simulates a multi-turn user session, tracking context across turns.

**JSON Schema**:
```json
[
  {
    "id": "string (unique identifier for the conversation)",
    "turns": [
      {
        "user_query": "string (the natural language query from the user)",
        "expected_operation": "string (the expected routing intent: NEW, REFINE, CLARIFY, REFUSE)",
        "gold_sql": "string (Optional. The expected ground-truth PostgreSQL query)"
      }
    ]
  }
]
```

**Constraints**:
- Each conversation must have 3 to 5 turns.
- `gold_sql` is required if `expected_operation` is `NEW` or `REFINE`.
- `gold_sql` should be omitted if `expected_operation` is `CLARIFY` or `REFUSE`.
"""
