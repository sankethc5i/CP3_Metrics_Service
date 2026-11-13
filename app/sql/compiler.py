"""Deterministic scoping of catalog formulas; no model-authored SQL is accepted."""

from dataclasses import dataclass
from typing import Any

from sqlglot import exp, parse_one

from app.config import AS_OF_DATE
from app.sql.schema import SCHEMA
from app.semantic.models import Catalog, Dimension
from app.semantic.policy import ValidatedRequest, validate_request

KEYS = {"orders":"order_id","order_items":"order_item_id","customers":"customer_id","sessions":"session_id"}


@dataclass(frozen=True)
class CompiledQuery:
    """SQL text separated from all user-supplied literal parameters."""

    sql: str
    parameters: dict[str,Any]
    metric_id: str
    dimensions: tuple[str,...]
    max_rows: int


def dimension_expression(dimension: Dimension, base: str) -> str:
    """Build a governed source-column or calendar-grain expression."""
    column = dimension.sources[base].column
    if dimension.transform == "month":
        return f"STRFTIME('%Y-%m', {column})"
    if dimension.transform == "quarter":
        return f"STRFTIME('%Y', {column}) || '-Q' || CAST((CAST(STRFTIME('%m', {column}) AS INTEGER)+2)/3 AS INTEGER)"
    return column


def compile_request(request: ValidatedRequest, catalog: Catalog, max_rows: int = 100, include_components: bool = False) -> CompiledQuery:
    """Compile only catalog formulas, paths and validated identifiers with bound values."""
    # Recheck at this boundary so manually constructed ValidatedRequest objects
    # cannot smuggle an alternate metric definition or identifier into the compiler.
    request = validate_request(request.arguments,catalog)
    if not 1 <= max_rows <= 500:
        raise ValueError("Row limit must be between one and five hundred")
    metric,arguments = request.metric,request.arguments
    base = metric.base_table
    dimensions = {d.id:d for d in catalog.dimensions}
    grouped = list(arguments.dimensions)
    if arguments.grain != "total":
        grouped.append(arguments.grain)
    required = set(grouped) | {f.dimension for f in arguments.filters if f.dimension != "status"}
    joined = {base}
    joins: list[str] = []
    # Metadata was schema-validated by the catalog loader before service construction.
    for name in sorted(required):
        for edge in dimensions[name].sources[base].joins:
            target = edge.target.split(".")[0]
            if target not in joined:
                joins.append(f"JOIN {target} ON {edge.source}={edge.target}")
                joined.add(target)
    if base == "order_items" and "orders" not in joined:
        joins.insert(0,"JOIN orders ON order_items.order_id=orders.order_id")
        joined.add("orders")
    date_column = str(metric.default_filters["date_column"])
    predicates = [f"{date_column} >= :start_date",f"{date_column} < :end_date"]
    parameters: dict[str,Any] = {"start_date":request.start,"end_date":request.end,"as_of_date":AS_OF_DATE.isoformat()}
    if "status" in metric.default_filters:
        predicates.append("orders.status IN ('completed','returned')")
    for index,item in enumerate(arguments.filters):
        column = "orders.status" if item.dimension == "status" else dimension_expression(dimensions[item.dimension],base)
        placeholders = []
        for number,value in enumerate(item.values):
            key = f"filter_{index}_{number}"
            parameters[key] = value
            placeholders.append(":"+key)
        predicates.append(column+" IN ("+", ".join(placeholders)+")")
    projections = [f"{base}.{KEYS[base]} AS scope_id"]
    projections += [f"{dimension_expression(dimensions[name],base)} AS {name}" for name in grouped]
    scope = "SELECT "+", ".join(projections)+" FROM "+base+" "+" ".join(joins)+" WHERE "+" AND ".join(predicates)
    group_where = " AND ".join(f"scope.{name} IS g.{name}" for name in grouped)
    membership = "SELECT scope_id FROM scope"+(" WHERE "+group_where if grouped else "")
    key_map = {base:KEYS[base]}
    if base in {"orders","order_items"}:
        key_map["commerce_lines"] = KEYS[base]

    def scoped(node: exp.Expression) -> exp.Expression:
        if isinstance(node,exp.Table) and node.name in key_map:
            relation = "line_snapshot" if node.name == "commerce_lines" else node.name
            columns = ", ".join(SCHEMA[node.name])
            query = f"SELECT {columns} FROM {relation} WHERE {key_map[node.name]} IN ({membership})"
            return parse_one(query,read="sqlite").subquery(alias=node.alias_or_name)
        return node

    def scoped_formula(sql: str) -> str:
        return parse_one(sql,read="sqlite").transform(scoped).sql(dialect="sqlite")

    formula = scoped_formula(metric.formula)
    count = "SELECT COUNT(*) FROM scope"+(" WHERE "+group_where if grouped else "")
    selected = [f"g.{name} AS {name}" for name in grouped]
    selected += [f"({formula}) AS {metric.id}",f"({count}) AS __source_count"]
    components: list[str] = []
    if include_components and metric.numerator and metric.denominator:
        components = ["__numerator","__denominator"]
        selected += [f"({scoped_formula(metric.numerator)}) AS __numerator",
                     f"({scoped_formula(metric.denominator)}) AS __denominator"]
    snapshot = ("line_snapshot AS MATERIALIZED (SELECT "+", ".join(SCHEMA["commerce_lines"])+" FROM commerce_lines), ") if "commerce_lines" in metric.formula else ""
    ctes = "WITH "+snapshot+"scope AS MATERIALIZED ("+scope+")"
    if grouped:
        ctes += ", groups AS (SELECT DISTINCT "+", ".join(grouped)+" FROM scope)"
    inner = "SELECT "+", ".join(selected)+(" FROM groups g" if grouped else "")
    columns = ", ".join([*grouped,metric.id,*components])
    sql = ctes+" SELECT "+columns+" FROM ("+inner+") AS answer_rows WHERE __source_count > 0 AND "+metric.id+" IS NOT NULL"
    if grouped:
        sql += " ORDER BY "+", ".join(grouped)
    sql += f" LIMIT {max_rows}"
    return CompiledQuery(sql,parameters,metric.id,tuple(grouped),max_rows)
