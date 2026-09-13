import pytest
from talk2db.guardrails import validate_and_format_sql
from talk2db.exceptions import SQLSecurityViolation

def test_valid_select_query():
    """Test that a basic SELECT query passes and gets formatted."""
    sql = "SELECT id, name FROM farmer WHERE is_active = true"
    formatted = validate_and_format_sql(sql)
    assert "SELECT" in formatted.upper()
    assert "farmer" in formatted.lower()

def test_injects_limit():
    """Test that LIMIT 100 is injected when missing."""
    sql = "SELECT * FROM plot"
    formatted = validate_and_format_sql(sql)
    assert "LIMIT 100" in formatted.upper()

def test_retains_existing_limit():
    """Test that an existing LIMIT is not overridden if present."""
    sql = "SELECT * FROM plot LIMIT 10"
    formatted = validate_and_format_sql(sql)
    assert "LIMIT 10" in formatted.upper()
    assert "LIMIT 100" not in formatted.upper()

def test_blocks_drop_table():
    """Test that destructive queries are blocked."""
    sql = "DROP TABLE farmer"
    with pytest.raises(SQLSecurityViolation, match="Destructive or non-SELECT"):
        validate_and_format_sql(sql)

def test_blocks_delete():
    sql = "DELETE FROM plot WHERE id = 1"
    with pytest.raises(SQLSecurityViolation, match="Destructive or non-SELECT"):
        validate_and_format_sql(sql)

def test_blocks_update():
    sql = "UPDATE farmer SET is_active = false"
    with pytest.raises(SQLSecurityViolation, match="Destructive or non-SELECT"):
        validate_and_format_sql(sql)

def test_blocks_multiple_statements():
    """Test that multi-statement SQL injection is blocked."""
    sql = "SELECT * FROM farmer; DROP TABLE plot;"
    with pytest.raises(SQLSecurityViolation, match="Multiple SQL statements detected"):
        validate_and_format_sql(sql)

def test_invalid_sql_syntax():
    """Test that malformed SQL is caught by the parser."""
    sql = "SELECT * FROM WHERE id ="
    with pytest.raises(SQLSecurityViolation, match="SQL Syntax Error"):
        validate_and_format_sql(sql)

def test_blocks_truncate():
    """Test that TRUNCATE is blocked."""
    sql = "TRUNCATE TABLE plot"
    with pytest.raises(SQLSecurityViolation, match="Destructive or non-SELECT"):
        validate_and_format_sql(sql)

def test_blocks_execute():
    """Test that EXECUTE is blocked."""
    sql = "EXECUTE my_procedure()"
    with pytest.raises(SQLSecurityViolation, match="Destructive or non-SELECT"):
        validate_and_format_sql(sql)
