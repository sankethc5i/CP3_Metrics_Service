"""Numeric provenance, deterministic calculations and safe template fallback."""

import pytest

from app.answers.calculator import calculate, per_order, percentage_change
from app.answers.render import render


def test_only_references_are_substituted() -> None:
    """Template values come exclusively from structured result/calculation maps."""
    assert render("Revenue: {{result.net_revenue}}; share: {{calc.share}}%.",{"net_revenue":123.45},{"share":25}) == "Revenue: 123.45; share: 25%."


@pytest.mark.parametrize("template",["Revenue is 999.","Revenue is nine.","Revenue is ９９９.",
    "Revenue is {{result.missing}}.","Revenue is {{result.net_revenue + 2}}.","No numerical reference."])
def test_raw_or_fabricated_numbers_rejected(template: str) -> None:
    """Digits, number words, Unicode numbers, expressions and unknown refs fail."""
    with pytest.raises(ValueError):
        render(template,{"net_revenue":123},{})


def test_calculator() -> None:
    """Per-order figures, changes, shares and percentages use deterministic operands."""
    assert per_order(120,3)==40
    assert per_order(120,0) is None
    assert percentage_change(150,100)==50
    rows = [{"month":"2026-09","net_revenue":100},{"month":"2026-10","net_revenue":150}]
    result = calculate(rows,"net_revenue","USD",("month",))
    assert result["row0_visible_share_percentage"]==40
    assert result["row1_change_since_previous_observed_period_percentage"]==50
    assert calculate([{"conversion_rate":0.25}],"conversion_rate","ratio",())["row0_percentage"]==25
