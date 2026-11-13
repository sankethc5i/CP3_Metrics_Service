"""Exhaustive governed SQL matrix, independent references and bypass regressions."""

from pathlib import Path
import sqlite3

import pytest
import yaml

from app.config import DATABASE_PATH, ROOT
from app.db.executor import execute_query
from app.evaluation.dataset import load_cases
from app.evaluation.ground_truth import verify_answer
from app.evaluation.metrics import exact_rows
from app.evaluation.validator import benchmark_validator
from app.semantic.loader import load_catalog
from app.semantic.policy import PolicyError, validate_request
from app.sql.compiler import compile_request
from app.sql.validation import validate_query
from tests.test_pipeline_safety import arguments

CATALOG = yaml.safe_load((ROOT/"semantic"/"metrics.yaml").read_text(encoding="utf-8"))
MATRIX = [(m["id"], d, g) for m in CATALOG["metrics"]
          for d in [None, *(x for x in m["allowed_dimensions"] if x not in {"month", "quarter"})]
          for g in ["total", *m["allowed_time_grains"]]]


@pytest.mark.parametrize("metric,dimension,grain", MATRIX)
def test_complete_compiler_matrix(metric: str, dimension: str | None, grain: str, warehouse: Path) -> None:
    """Every permitted metric/single-dimension/time-grain compiles and executes."""
    catalog = load_catalog(database=warehouse)
    request = arguments(metric, dimensions=[dimension] if dimension else [], grain=grain)
    query = compile_request(validate_request(request, catalog), catalog, max_rows=500, include_components=True)
    validate_query(query.sql, 500)
    rows = execute_query(query, warehouse)
    assert rows and all(metric in row for row in rows)
    assert all((dimension in row if dimension else True) and (grain in row if grain != "total" else True) for row in rows)


@pytest.mark.parametrize("bypass", ["union_nested", "star", "qualified_star", "missing_formula", "wrong_formula", "literal_formula"])
def test_each_original_validator_miss_is_rejected(bypass: str) -> None:
    """All six previously accepted planted negatives now fail the actual validator."""
    data = yaml.safe_load((ROOT/"eval"/"validator_queries.yaml").read_text())
    sql = next(c["sql"] for c in data["bad"] if c["id"] == bypass)
    with pytest.raises(ValueError):
        validate_query(sql)


@pytest.mark.parametrize("sql", [
    "SELECT x FROM (SELECT order_id AS x FROM orders INTERSECT SELECT customer_id AS x FROM customers) LIMIT 10",
    "SELECT x FROM (SELECT order_id AS x FROM orders EXCEPT SELECT customer_id AS x FROM customers) LIMIT 10",
    "WITH stolen AS (SELECT orders.* FROM orders) SELECT order_id FROM stolen LIMIT 10",
    "SELECT (SELECT tax FROM orders LIMIT 1) AS net_revenue LIMIT 10",
    "SELECT SUM(tax)+SUM(order_discount) AS net_revenue FROM orders LIMIT 10",
    "SELECT COUNT(*) AS orders FROM orders JOIN order_items ON orders.order_id=order_items.order_id LIMIT 10",
])
def test_new_nested_and_formula_bypasses(sql: str) -> None:
    """Nested set operations, hidden stars and renamed wrong formulas cannot bypass checks."""
    with pytest.raises(ValueError):
        validate_query(sql)


def test_validator_all_original_and_benign_queries() -> None:
    """Original probes are preserved: 32/32 caught and 0/10 benign false positives."""
    result = benchmark_validator(ROOT/"eval"/"validator_queries.yaml")
    assert result["bad_count"] == 32 and result["benign_count"] == 10
    assert result["catch_rate"] == 1 and result["false_positive_rate"] == 0


def test_reference_sample_uses_handwritten_sql(warehouse: Path) -> None:
    """Compile dev examples at all important grains and compare independent raw-table SQL."""
    _, cases = load_cases(ROOT/"eval"/"questions.yaml", DATABASE_PATH)
    catalog = load_catalog(database=warehouse)
    sample = [c for c in cases if c["expected_outcome"] in {"answer", "empty_result"}]
    for case in sample:
        query = compile_request(validate_request(arguments(case["expected_metric_id"],
            dimensions=case["dimensions"], grain=case["grain"], filters=case["filters"],
            time_range=case["time_range"]), catalog), catalog, max_rows=500)
        assert exact_rows(execute_query(query, warehouse), verify_answer(case, warehouse))


def test_order_line_counts_and_no_revenue_fanout(warehouse: Path, db: sqlite3.Connection) -> None:
    """Raw order-grain subtraction and grouped line revenue reconcile without fan-out."""
    catalog = load_catalog(database=warehouse)
    def result(metric: str, **kwargs: object):
        return execute_query(compile_request(validate_request(arguments(metric, **kwargs), catalog), catalog, max_rows=500), warehouse)
    assert result("orders")[0]["orders"] == db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 400
    assert result("order_lines")[0]["order_lines"] == db.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 580
    expected = db.execute("""SELECT SUM((SELECT SUM(i.quantity*i.unit_price-i.line_discount)
        FROM order_items i WHERE i.order_id=o.order_id)-o.order_discount-
        COALESCE((SELECT SUM(r.refund_amount) FROM returns r JOIN order_items i ON i.order_item_id=r.order_item_id
        WHERE i.order_id=o.order_id),0))/100.0 FROM orders o WHERE status IN ('completed','returned')""").fetchone()[0]
    assert result("net_revenue")[0]["net_revenue"] == pytest.approx(expected)
    for dimension in ("category", "brand", "order_region", "customer_region", "device"):
        assert sum(r["net_revenue"] for r in result("net_revenue", dimensions=[dimension])) == pytest.approx(expected)


@pytest.mark.parametrize("field,value,outcome", [
    ("dimensions", ["category; DROP TABLE orders"], "refuse"),
    ("dimensions", ["employee_salary"], "refuse"),
    ("filters", [{"dimension": "brand", "operator": "eq", "values": ["Cedar' OR 1=1 --"]}], "clarify"),
    ("filters", [{"dimension": "brand) UNION SELECT password", "operator": "eq", "values": ["Cedar"]}], "refuse"),
])
def test_malicious_arguments_stop_before_sql(field: str, value: object, outcome: str, warehouse: Path) -> None:
    """Compiler revalidation rejects malicious identifiers and filter literals."""
    catalog = load_catalog(database=warehouse)
    with pytest.raises(PolicyError) as error:
        compile_request(validate_request(arguments(**{field: value}), catalog), catalog)
    assert error.value.outcome == outcome
