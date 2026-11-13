"""Compiled formulas reconcile with the governed baseline and preserve grain."""

from pathlib import Path
import sqlite3

import pytest

from app.config import AS_OF_DATE
from app.db.executor import execute_query
from app.semantic.loader import load_catalog
from app.semantic.policy import validate_request
from app.sql.compiler import compile_request
from tests.test_pipeline_safety import arguments


@pytest.mark.parametrize("metric_id",["order_lines","orders","units_sold","gross_revenue","net_revenue","aov","gross_margin","discount_rate","cancellation_rate","return_rate","new_customers","repeat_purchase_rate","conversion_rate","discounts","refunds"])
def test_all_compiled_totals(metric_id: str, warehouse: Path, db: sqlite3.Connection) -> None:
    """Compiler totals equal independently authored catalog formulas for every metric."""
    catalog = load_catalog(database=warehouse)
    valid = validate_request(arguments(metric_id),catalog)
    expected = db.execute(valid.metric.formula,{"as_of_date":AS_OF_DATE.isoformat()}).fetchone()[0]
    query = compile_request(valid,catalog)
    assert execute_query(query,warehouse)[0][metric_id] == pytest.approx(expected)


@pytest.mark.parametrize("metric_id,dimension",[("net_revenue","category"),("aov","order_region"),("repeat_purchase_rate","device"),("conversion_rate","traffic_source"),("new_customers","age_group"),("order_lines","brand")])
def test_grouped_metrics(metric_id: str, dimension: str, warehouse: Path) -> None:
    """Every important base grain supports safe grouped evaluation."""
    catalog = load_catalog(database=warehouse)
    query = compile_request(validate_request(arguments(metric_id,dimensions=[dimension],grain="quarter"),catalog),catalog,max_rows=100)
    rows = execute_query(query,warehouse)
    assert rows and all(set(row)=={dimension,"quarter",metric_id} for row in rows)


def test_grouped_net_totals_and_filters(warehouse: Path, db: sqlite3.Connection) -> None:
    """Splitting categories preserves discounts and filter parameters narrow results."""
    catalog = load_catalog(database=warehouse)
    grouped = compile_request(validate_request(arguments(dimensions=["category"]),catalog),catalog)
    rows = execute_query(grouped,warehouse)
    total = execute_query(compile_request(validate_request(arguments(),catalog),catalog),warehouse)[0]["net_revenue"]
    assert sum(row["net_revenue"] for row in rows) == pytest.approx(total)
    filtered = compile_request(validate_request(arguments(dimensions=["category"],filters=[{"dimension":"category","operator":"eq","values":["Books"]}]),catalog),catalog)
    assert execute_query(filtered,warehouse) == [row for row in rows if row["category"]=="Books"]


def test_empty_valid_period(warehouse: Path) -> None:
    """A valid query with no matching base rows returns no synthetic aggregate row."""
    catalog = load_catalog(database=warehouse)
    request = arguments(time_range={"start":"2020-01-01","end":"2020-02-01","relative":None})
    assert execute_query(compile_request(validate_request(request,catalog),catalog),warehouse) == []
