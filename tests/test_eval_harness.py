from eval.run_eval import compare_results, normalize_result_set
from decimal import Decimal

def test_comparator_exact_match():
    gold_sql = "SELECT id, name FROM farmer"
    gen_sql = "SELECT id, name FROM farmer"
    gold = [{"id": 1, "name": "John"}]
    gen = [{"id": 1, "name": "John"}]
    assert compare_results(gold_sql, gen_sql, gold, gen) is True

def test_comparator_extra_columns_pass():
    # SELECT * is handled by falling back to key mapping.
    gold_sql = "SELECT name FROM farmer"
    gen_sql = "SELECT * FROM farmer"
    gold = [{"name": "John"}]
    gen = [{"id": 1, "name": "John", "district": "Pune"}]
    assert compare_results(gold_sql, gen_sql, gold, gen) is True

def test_comparator_aliases_handled():
    # Explicit projections are handled by AST index mapping, completely ignoring PostgreSQL aliases!
    gold_sql = "SELECT SUM(actual_yield)"
    gen_sql = "SELECT SUM(actual_yield) AS total_yield"
    gold = [{"sum": 100}]
    gen = [{"total_yield": 100}] 
    assert compare_results(gold_sql, gen_sql, gold, gen) is True

def test_comparator_duplicate_expressions_handled():
    # If the query asks for the exact same expression twice, 
    # the index mapper must handle 1-to-1 matching properly.
    gold_sql = "SELECT SUM(actual_yield) AS act1, SUM(actual_yield) AS act2"
    gen_sql = "SELECT SUM(actual_yield) AS t1, SUM(actual_yield) AS t2"
    gold = [{"act1": 100, "act2": 200}]
    gen = [{"t1": 100, "t2": 200}] 
    assert compare_results(gold_sql, gen_sql, gold, gen) is True

def test_comparator_missing_columns_fails():
    gold_sql = "SELECT act_yield"
    gen_sql = "SELECT total_yield" 
    gold = [{"act_yield": 100}]
    gen = [{"total_yield": 100}] 
    assert compare_results(gold_sql, gen_sql, gold, gen) is False

def test_comparator_different_row_order():
    gold_sql = "SELECT id FROM plot"
    gen_sql = "SELECT id FROM plot"
    gold = [{"id": 1}, {"id": 2}, {"id": 3}]
    gen = [{"id": 3}, {"id": 1}, {"id": 2}]
    assert compare_results(gold_sql, gen_sql, gold, gen) is True

def test_comparator_extra_rows_fails():
    gold_sql = "SELECT id FROM plot"
    gen_sql = "SELECT id FROM plot"
    gold = [{"id": 1}]
    gen = [{"id": 1}, {"id": 2}]
    assert compare_results(gold_sql, gen_sql, gold, gen) is False

def test_comparator_duplicate_rows_preserved():
    gold_sql = "SELECT id FROM plot"
    gen_sql = "SELECT id FROM plot"
    gold = [{"id": 1}, {"id": 1}]
    gen_missing_duplicate = [{"id": 1}]
    gen_correct_duplicates = [{"id": 1}, {"id": 1}]
    
    assert compare_results(gold_sql, gen_sql, gold, gen_missing_duplicate) is False
    assert compare_results(gold_sql, gen_sql, gold, gen_correct_duplicates) is True

def test_comparator_type_stability():
    gold = [{"val1": Decimal('10.12345'), "val2": None, "val3": "Test"}]
    gen_subset = [{"val1": Decimal('10.1234'), "val2": None, "val3": "Test"}]
    assert normalize_result_set(gold) == normalize_result_set(gen_subset)
