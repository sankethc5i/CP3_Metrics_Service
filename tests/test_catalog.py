"""Catalog validation, safe dimensions, and independently reconciled metrics."""

import copy
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.config import AS_OF_DATE, CATALOG_PATH
from app.semantic.loader import dimension_join_sql, load_catalog
from app.semantic.models import Catalog
from app.sql.validation import validate_select


def _raw() -> dict[str, Any]:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_queries_and_join_paths(warehouse: Path, db: sqlite3.Connection) -> None:
    """Resolve every formula and prove every permitted dimension preserves row count."""
    catalog = load_catalog(database=warehouse)
    assert len(catalog.metrics) == 15
    assert len(catalog.dimensions) == 9
    dimensions = {d.id:d for d in catalog.dimensions}
    for metric in catalog.metrics:
        rows = db.execute(metric.formula,{"as_of_date":AS_OF_DATE.isoformat()}).fetchall()
        assert len(rows) == 1 and len(rows[0]) == 1
        if metric.unit == "ratio":
            assert rows[0][0] is None or 0 <= rows[0][0] <= 1
        original = db.execute(f'SELECT COUNT(*) FROM "{metric.base_table}"').fetchone()[0]
        for dimension_id in metric.allowed_dimensions:
            dimension = dimensions[dimension_id]
            source = dimension.sources[metric.base_table]
            joins = dimension_join_sql(db,metric.base_table,source)
            assert db.execute("SELECT COUNT(*) "+joins).fetchone()[0] == original
            assert sum(r[0] for r in db.execute(f"SELECT COUNT(*) {joins} GROUP BY {source.column}")) == original


def test_independent_financial_reconciliation(warehouse: Path, db: sqlite3.Connection) -> None:
    """Compare governed SQL to independent Python aggregation at the correct grains."""
    metrics = {m.id:m for m in load_catalog(database=warehouse).metrics}
    def value(metric_id: str) -> float:
        return db.execute(metrics[metric_id].formula,{"as_of_date":AS_OF_DATE.isoformat()}).fetchone()[0]
    eligible = {r["order_id"]:r for r in db.execute("SELECT * FROM orders") if r["status"] in ("completed","returned")}
    lines = [r for r in db.execute("SELECT * FROM order_items") if r["order_id"] in eligible]
    gross = sum(r["quantity"]*r["unit_price"] for r in lines)
    discounts = sum(r["line_discount"] for r in lines) + sum(r["order_discount"] for r in eligible.values())
    line_ids = {r["order_item_id"] for r in lines}
    refunds = sum(r["refund_amount"] for r in db.execute("SELECT * FROM returns") if r["order_item_id"] in line_ids)
    costs = dict(db.execute("SELECT product_id,unit_cost FROM products"))
    cogs = sum(r["quantity"]*costs[r["product_id"]] for r in lines)
    assert value("gross_revenue") == gross/100
    assert value("discounts") == discounts/100
    assert value("refunds") == refunds/100
    assert value("net_revenue") == (gross-discounts-refunds)/100
    assert value("gross_margin") == (gross-discounts-refunds-cogs)/100
    assert value("aov") == pytest.approx((gross-discounts-refunds)/100/len(eligible))
    assert value("discount_rate") == pytest.approx(discounts/gross)
    assert value("orders") == 400
    assert value("order_lines") == 580
    assert value("units_sold") == sum(r["quantity"] for r in lines)
    assert value("conversion_rate") == pytest.approx(400/2400)
    assert value("cancellation_rate") == pytest.approx(db.execute("SELECT COUNT(*) FROM orders WHERE status='cancelled'").fetchone()[0]/400)
    assert value("new_customers") == 160
    assert value("return_rate") == pytest.approx(len(list(db.execute("SELECT * FROM returns")))/len(lines))
    purchases: dict[int,int] = {}
    for order in eligible.values():
        purchases[order["customer_id"]] = purchases.get(order["customer_id"],0)+1
    assert value("repeat_purchase_rate") == pytest.approx(sum(n>=2 for n in purchases.values())/len(purchases))


def test_category_net_revenue_reconciles(db: sqlite3.Connection) -> None:
    """Dimension splits sum to the same net cents as the unsplit line fact."""
    totals = db.execute("""SELECT p.category,SUM(l.line_total-l.allocated_order_discount-l.refund_cents)
        FROM commerce_lines l JOIN products p USING(product_id)
        WHERE l.status IN ('completed','returned') GROUP BY p.category""").fetchall()
    overall = db.execute("""SELECT SUM(line_total-allocated_order_discount-refund_cents)
        FROM commerce_lines WHERE status IN ('completed','returned')""").fetchone()[0]
    assert sum(row[1] for row in totals) == overall


@pytest.mark.parametrize("change",["unknown_column","unknown_table","bad_dimension","fanout","bad_sql","extra","unknown_id","ambiguity"])
def test_reject_invalid_catalog(change: str, warehouse: Path, tmp_path: Path) -> None:
    """Catalog errors fail before execution or any metric selection."""
    raw = copy.deepcopy(_raw())
    if change == "unknown_column":
        raw["metrics"][0]["formula"] = "SELECT SUM(nonexistent) FROM order_items"
    elif change == "unknown_table":
        raw["metrics"][0]["formula"] = "SELECT COUNT(*) FROM nonexistent"
    elif change == "bad_dimension":
        raw["metrics"][0]["allowed_dimensions"].append("not_a_dimension")
    elif change == "fanout":
        raw["dimensions"][0]["sources"]["orders"] = {
            "column":"order_items.order_id", "joins":[{"source":"orders.order_id","target":"order_items.order_id"}]}
    elif change == "bad_sql":
        raw["metrics"][0]["formula"] = "DELETE FROM orders"
    elif change == "extra":
        raw["metrics"][0]["unexpected"] = True
    elif change == "unknown_id":
        raw["metrics"][1]["id"] = raw["metrics"][0]["id"]
    elif change == "ambiguity":
        raw["metrics"][0]["synonyms"].append("revenue")
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(raw),encoding="utf-8")
    with pytest.raises((ValueError,ValidationError)):
        load_catalog(path,warehouse)


def test_clarification_rules_and_date_anchor() -> None:
    """Neither deliberate ambiguity has an implicit default."""
    catalog = Catalog.model_validate(_raw())
    assert catalog.as_of_date == AS_OF_DATE.isoformat()
    assert {a.term: a.choices for a in catalog.ambiguities} == {
        "revenue":["gross_revenue","net_revenue"],"region":["order_region","customer_region"]}
    assert all(a.outcome == "clarify" for a in catalog.ambiguities)


@pytest.mark.parametrize("sql",["DELETE FROM orders","SELECT * FROM orders; SELECT 1",
    "ATTACH DATABASE 'other.db' AS other","SELECT load_extension('bad')",
    "SELECT * FROM missing_table","SELECT * FROM other.orders"])
def test_reject_unsafe_sql(sql: str) -> None:
    """Reject mutations, multiple statements and ungoverned relations/functions."""
    with pytest.raises(ValueError):
        validate_select(sql,{"orders"})


def test_zero_denominator(warehouse: Path, db: sqlite3.Connection) -> None:
    """An empty time window yields NULL for every ratio, including AOV."""
    for metric in load_catalog(database=warehouse).metrics:
        if metric.denominator:
            assert db.execute(metric.formula,{"as_of_date":"1900-01-01"}).fetchone()[0] is None
