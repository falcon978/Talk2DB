import pytest
from eval.run_eval import normalize_row, normalize_result_set

def test_normalize_row_sorts_values():
    row = {"Name": "John", "Age": 30}
    normalized = normalize_row(row)
    # Should sort values by type-aware key: 30, "John"
    assert normalized == (30, "John")

def test_normalize_row_rounds_floats():
    row = {"yield": 12.3456789, "area": 1.1}
    normalized = normalize_row(row)
    assert normalized == (1.1, 12.3457)

def test_normalize_result_set_ignores_row_order():
    set1 = [{"id": 1}, {"id": 2}]
    set2 = [{"id": 2}, {"id": 1}]
    
    assert normalize_result_set(set1) == normalize_result_set(set2)

def test_normalize_result_set_ignores_column_order():
    set1 = [{"id": 1, "name": "A"}]
    set2 = [{"name": "A", "id": 1}]
    
    assert normalize_result_set(set1) == normalize_result_set(set2)

def test_normalize_result_set_exact_matching():
    set1 = [{"id": 1, "val": 10.12341}]
    set2 = [{"id": 1, "val": 10.12344}]
    # Both round to 10.1234
    assert normalize_result_set(set1) == normalize_result_set(set2)
    
    set3 = [{"id": 1, "val": 10.1235}] # Rounds differently
    assert normalize_result_set(set1) != normalize_result_set(set3)
