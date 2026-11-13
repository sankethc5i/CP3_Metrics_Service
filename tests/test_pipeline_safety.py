"""Separate proofs for argument validation, policy, compiler, AST and execution."""

from dataclasses import replace
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import AS_OF_DATE
from app.db.executor import execute_query
from app.llm.schemas import SelectMetric
from app.semantic.dates import resolve_dates
from app.semantic.loader import load_catalog
from app.semantic.policy import PolicyError, ValidatedRequest, metric_exists, validate_request, VALUES
from app.sql.compiler import CompiledQuery, compile_request
from app.sql.validation import validate_query


def arguments(metric: str = "net_revenue", **updates: object) -> SelectMetric:
    """Create a typed default request with selected test overrides."""
    raw = {"metric_id":metric,"dimensions":[],"filters":[],"grain":"total",
        "time_range":{"start":None,"end":None,"relative":"all_time"},**updates}
    return SelectMetric.model_validate(raw)


def test_layer_one_pydantic() -> None:
    """Unknown fields and unsupported filter operators fail structural validation."""
    with pytest.raises(ValidationError):
        arguments(sql="DROP TABLE orders")
    with pytest.raises(ValidationError):
        arguments(filters=[{"dimension":"category","operator":"raw_sql","values":["1=1"]}])


def test_layer_two_metric_id(warehouse: Path) -> None:
    """Well-formed IDs still need to exist in the governed catalog."""
    with pytest.raises(PolicyError) as failure:
        metric_exists(arguments("customer_lifetime_value"),load_catalog(database=warehouse))
    assert failure.value.outcome == "refuse"


@pytest.mark.parametrize("overrides,outcome",[
    ({"dimensions":["category; DROP TABLE orders"]},"refuse"),
    ({"metric_id":"orders","dimensions":["category"]},"refuse"),
    ({"filters":[{"dimension":"category","operator":"eq","values":["Unknown"]}]},"clarify"),
    ({"filters":[{"dimension":"category","operator":"eq","values":["Books' OR 1=1 --"]}]},"clarify"),
    ({"filters":[{"dimension":"customer_name","operator":"eq","values":["x"]}]},"refuse"),
])
def test_layer_three_allow_lists(overrides: dict, outcome: str, warehouse: Path) -> None:
    """Distinguish unsupported identifiers from unknown literal values."""
    with pytest.raises(PolicyError) as failure:
        validate_request(arguments(**overrides),load_catalog(database=warehouse))
    assert failure.value.outcome == outcome


def test_layer_three_time_grain(warehouse: Path) -> None:
    """Catalog grain restrictions apply even to a schema-valid month grain."""
    catalog = load_catalog(database=warehouse)
    metric = next(m for m in catalog.metrics if m.id=="net_revenue")
    metric.allowed_time_grains = ["quarter"]
    with pytest.raises(PolicyError):
        validate_request(arguments(grain="month"),catalog)


def test_layer_four_parameterization_and_forgery(warehouse: Path) -> None:
    """Even an approved literal with SQL syntax remains a bound parameter."""
    catalog = load_catalog(database=warehouse)
    literal = "Books' OR 1=1 --"
    with patch.dict(VALUES,{"category":(*VALUES["category"],literal)}):
        validated = validate_request(arguments(filters=[{"dimension":"category","operator":"eq","values":[literal]}]),catalog)
        query = compile_request(validated,catalog)
        assert literal not in query.sql
        assert literal in query.parameters.values()
        validate_query(query.sql)
        assert execute_query(query,warehouse) == []
    valid = validate_request(arguments(),catalog)
    malicious = valid.arguments.model_copy(update={"dimensions":["sqlite_master.name"]})
    with pytest.raises(PolicyError):
        compile_request(ValidatedRequest(malicious,valid.metric,valid.start,valid.end),catalog)


@pytest.mark.parametrize("sql",[
    "SELECT name FROM sqlite_master LIMIT 5",
    "SELECT password FROM customers LIMIT 5",
    "SELECT * FROM orders -- comment\n LIMIT 5",
    "SELECT * FROM orders /* comment */ LIMIT 5",
    "PRAGMA table_info(orders)","ATTACH DATABASE 'bad.db' AS bad",
    "DROP TABLE orders","DELETE FROM orders","UPDATE orders SET tax=0",
    "SELECT * FROM orders LIMIT 2; SELECT * FROM customers LIMIT 2",
    "SELECT * FROM orders","SELECT * FROM orders LIMIT 501",
    "SELECT * FROM orders LIMIT :limit",
    "SELECT * FROM orders LIMIT 2 OFFSET 1",
    "SELECT load_extension('file') LIMIT 2",
    "WITH orders AS (SELECT 1 AS order_id) SELECT * FROM orders LIMIT 2",
])
def test_layer_five_ast(sql: str) -> None:
    """Reject every forbidden SQL class, unknown column and unbounded query."""
    with pytest.raises(ValueError):
        validate_query(sql)


def test_failed_validation_never_reaches_database(warehouse: Path) -> None:
    """Executor revalidation prevents unsafe SQL from reaching even a connection."""
    with patch("app.db.executor.connect_readonly") as connect:
        with pytest.raises(ValueError):
            execute_query(CompiledQuery("DELETE FROM orders",{},"orders",(),100),warehouse)
        connect.assert_not_called()


def test_layer_six_timeout_and_row_cap(warehouse: Path) -> None:
    """Execution enforces deadlines and the compiled SQL bounds returned rows."""
    catalog = load_catalog(database=warehouse)
    query = compile_request(validate_request(arguments(grain="month"),catalog),catalog,max_rows=2)
    assert len(execute_query(query,warehouse)) <= 2
    with pytest.raises(sqlite3.OperationalError,match="interrupted"):
        execute_query(query,warehouse,timeout=0.00000001)


def test_relative_date_anchor() -> None:
    """Last month and year are resolved relative to the frozen date, not today."""
    spec = arguments(time_range={"start":None,"end":None,"relative":"last_month"}).time_range
    assert resolve_dates(spec) == ("2026-10-01","2026-11-01")
    assert resolve_dates(arguments(time_range={"start":None,"end":None,"relative":"last_quarter"}).time_range) == ("2026-07-01","2026-10-01")
