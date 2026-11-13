"""Derived numbers computed exclusively by deterministic application code."""

from decimal import Decimal
from typing import Any

ADDITIVE = {"order_lines","orders","units_sold","gross_revenue","net_revenue","gross_margin","discounts","refunds","new_customers"}


def divide(numerator: int | float | Decimal, denominator: int | float | Decimal) -> float | None:
    """Return a deterministic quotient or None for a zero denominator."""
    return float(Decimal(str(numerator))/Decimal(str(denominator))) if denominator else None


def per_order(revenue: int | float, orders: int | float) -> float | None:
    """Compute per-order value from query-sourced operands."""
    return divide(revenue,orders)


def percentage_change(current: int | float, previous: int | float) -> float | None:
    """Compute percent change using a nonzero previous value."""
    change = divide(Decimal(str(current))-Decimal(str(previous)),previous)
    return float(Decimal(str(change))*100) if change is not None else None


def calculate(rows: list[dict[str,Any]], metric_id: str, unit: str, dimensions: tuple[str,...]) -> dict[str,Any]:
    """Expose percentage, visible-group share, and adjacent-period changes by name."""
    calculations: dict[str,Any] = {}
    if not rows:
        return calculations
    if metric_id == "aov":
        for index,row in enumerate(rows):
            if "__numerator" in row and "__denominator" in row:
                calculations[f"row{index}_per_order"] = per_order(row["__numerator"],row["__denominator"])
        if len(rows)==1 and "row0_per_order" in calculations:
            calculations["per_order"] = calculations["row0_per_order"]
    if unit == "ratio":
        for index,row in enumerate(rows):
            calculations[f"row{index}_percentage"] = float(Decimal(str(row[metric_id]))*100)
    if metric_id in ADDITIVE and len(rows)>1:
        total = sum(Decimal(str(row[metric_id])) for row in rows)
        for index,row in enumerate(rows):
            share = divide(row[metric_id],total)
            calculations[f"row{index}_visible_share_percentage"] = None if share is None else float(Decimal(str(share))*100)
    time_key = next((name for name in dimensions if name in {"month","quarter"}),None)
    if time_key:
        others = [name for name in dimensions if name != time_key]
        previous: dict[tuple[Any,...],tuple[str,int | float]] = {}
        for index,row in sorted(enumerate(rows),key=lambda item:str(item[1][time_key])):
            key = tuple(row[name] for name in others)
            period = str(row[time_key])
            last = previous.get(key)
            # Label the operation explicitly; missing periods are not imputed as zero.
            if last:
                calculations[f"row{index}_change_since_previous_observed_period_percentage"] = percentage_change(row[metric_id],last[1])
            previous[key] = (period,row[metric_id])
    return calculations
