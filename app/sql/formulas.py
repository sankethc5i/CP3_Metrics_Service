"""Check named metric projections against governed ASTs, independently of compilation."""

from functools import lru_cache

from sqlglot import exp, parse_one
import yaml

from app.config import CATALOG_PATH
from app.sql.schema import SCHEMA


@lru_cache(maxsize=4)
def _formulas(revision: int) -> dict[str, str]:
    data = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    return {m["id"]: parse_one(m["formula"], read="sqlite").sql(normalize=True) for m in data["metrics"]}


def _unscoped(node: exp.Expression) -> exp.Expression:
    if not isinstance(node, exp.Subquery) or node.alias not in SCHEMA:
        return node
    select = node.this
    if not isinstance(select, exp.Select):
        return node
    source = select.args.get("from_")
    table = source.this if source else None
    expected = "line_snapshot" if node.alias == "commerce_lines" else node.alias
    if not isinstance(table, exp.Table) or table.name != expected:
        return node
    columns = [p.name for p in select.expressions if isinstance(p, exp.Column)]
    if set(columns) != set(SCHEMA[node.alias]) or len(columns) != len(select.expressions):
        return node
    where = select.args.get("where")
    if not where or not any(t.name == "scope" for t in where.find_all(exp.Table)):
        return node
    if select.args.get("joins") or select.args.get("group") or select.args.get("distinct"):
        return node
    return exp.to_table(node.alias)


def validate_metric_formulas(tree: exp.Select) -> None:
    """Reject invented named metrics; accept exact scoped formulas or approved primitives."""
    formulas = _formulas(CATALOG_PATH.stat().st_mtime_ns)
    primitives = {
        "orders": ("COUNT(DISTINCT order_id)", "orders"),
        "order_lines": ("COUNT(*)", "order_items"),
        "units_sold": ("SUM(quantity)", "order_items"),
        "gross_revenue": ("SUM(quantity * unit_price) / 100.0", "order_items"),
        "new_customers": ("COUNT(*)", "customers"),
        "conversion_rate": ("1.0 * SUM(converted) / COUNT(*)", "sessions"),
    }
    for alias in tree.find_all(exp.Alias):
        if alias.alias not in formulas:
            continue
        expression = alias.this
        if isinstance(expression, exp.Subquery):
            normalized = expression.this.copy().transform(_unscoped).sql(normalize=True)
            if normalized == formulas[alias.alias]:
                continue
        primitive = primitives.get(alias.alias)
        if primitive:
            stripped = expression.copy()
            for column in stripped.find_all(exp.Column):
                column.set("table", None)
            select = alias.find_ancestor(exp.Select)
            source = select.args.get("from_") if select else None
            table = source.this if source else None
            if (alias.alias == "orders" and stripped == parse_one("COUNT(*)", read="sqlite")
                    and isinstance(table, exp.Table) and table.name == "orders" and not select.args.get("joins")):
                continue
            if (stripped == parse_one(primitive[0], read="sqlite")
                    and isinstance(table, exp.Table) and table.name == primitive[1]):
                continue
        raise ValueError("Named metric expression does not match its governed formula")
