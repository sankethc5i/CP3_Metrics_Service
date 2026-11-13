"""Cross-check reference financial SQL using raw-record integer arithmetic."""

from collections import defaultdict
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DATABASE_PATH, ROOT
from app.evaluation.dataset import load_cases
from app.evaluation.ground_truth import verify_answer
from app.evaluation.metrics import exact_rows


def main() -> None:
    """Verify scalar totals and category allocation independently, plus a worked order."""
    _, cases = load_cases(ROOT/"eval"/"questions.yaml", DATABASE_PATH)
    with closing(sqlite3.connect(DATABASE_PATH.resolve().as_uri()+"?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        orders = [dict(r) for r in db.execute("SELECT order_id,status,order_discount,shipping_cost,tax FROM orders")]
        lines = [dict(r) for r in db.execute("SELECT order_item_id,order_id,product_id,quantity,unit_price,line_discount,line_total FROM order_items")]
        categories = dict(db.execute("SELECT product_id,category FROM products"))
        refunds = dict(db.execute("SELECT order_item_id,SUM(refund_amount) FROM returns GROUP BY order_item_id"))
    by_order = defaultdict(list)
    for row in lines:
        by_order[row["order_id"]].append(row)
    gross, net, line_discount, order_discount, refund = 0, 0, 0, 0, 0
    category_net: dict[str, int] = defaultdict(int)
    sample = None
    for order in orders:
        if order["status"] not in {"completed", "returned"}:
            continue
        members = sorted(by_order[order["order_id"]], key=lambda r: r["order_item_id"])
        subtotal = sum(r["quantity"]*r["unit_price"]-r["line_discount"] for r in members)
        allocated = [order["order_discount"]*r["line_total"]//subtotal if subtotal else 0 for r in members]
        allocated[0] += order["order_discount"]-sum(allocated)
        gross += sum(r["quantity"]*r["unit_price"] for r in members)
        line_discount += sum(r["line_discount"] for r in members)
        order_discount += order["order_discount"]
        order_refund = sum(refunds.get(r["order_item_id"], 0) for r in members)
        refund += order_refund
        net += subtotal-order["order_discount"]-order_refund
        for row, discount in zip(members, allocated):
            category_net[categories[row["product_id"]]] += row["line_total"]-discount-refunds.get(row["order_item_id"], 0)
        if sample is None and len(members) >= 2 and order["order_discount"] > 0:
            sample = (order, members, allocated, order_refund)
    scalar = next(c for c in cases if c["expected_metric_id"] == "net_revenue" and c["category"] == "simple")
    assert exact_rows(verify_answer(scalar, DATABASE_PATH), [{"net_revenue": net/100}])
    # This audit's category sample is a dev-only independent SQL query, not a locked benchmark.
    category_case = {**scalar, "dimensions": ["category"],
                     "ground_truth": {"query": "category", "parameters": scalar["ground_truth"]["parameters"]}}
    assert exact_rows(verify_answer(category_case, DATABASE_PATH),
                      [{"category": k, "net_revenue": v/100} for k, v in category_net.items()])
    assert gross-line_discount-order_discount-refund == net
    assert sample is not None
    order, members, allocated, sample_refunds = sample
    out = ["# Independent ground-truth arithmetic audit", "",
           "No service/compiler/catalog formula/view is imported. SQL references are cross-checked against raw-record Python integer arithmetic.", "",
           "All amounts below are integer cents; divide by 100 only for displayed USD.", "",
           f"Full snapshot: {gross} gross - {line_discount} line discounts - {order_discount} order discounts - {refund} refunds = **{net} net**.", "",
           f"Worked order `{order['order_id']}` ({order['status']}):", "",
           "| Line | Quantity × unit price | Line discount | Line total | Allocated order discount |",
           "|---|---:|---:|---:|---:|"]
    for row, allocation in zip(members, allocated):
        out.append(f"| {row['order_item_id']} | {row['quantity']} × {row['unit_price']} | {row['line_discount']} | {row['line_total']} | {allocation} |")
    subtotal = sum(r["line_total"] for r in members)
    out += ["", f"Order net: {subtotal} - {order['order_discount']} - {sample_refunds} = {subtotal-order['order_discount']-sample_refunds} cents.",
            f"Allocation check: {' + '.join(str(v) for v in allocated)} = {order['order_discount']} cents.",
            f"Shipping {order['shipping_cost']} and tax {order['tax']} are excluded.", "",
            f"All {len(category_net)} category totals independently match the handwritten SQL, including allocation before category filtering.",
            "The scalar and category cross-checks passed. This audit constructs/verifies reference data; it does not evaluate locked questions."]
    target = ROOT/"eval"/"reports"/"ground_truth_audit.md"
    target.parent.mkdir(exist_ok=True, parents=True)
    target.write_text("\n".join(out)+"\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
