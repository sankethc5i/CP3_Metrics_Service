# Governed metric catalog

Authoritative definitions: `semantic/metrics.yaml`; loader: `app/semantic/loader.py`.
Each formula is a complete hand-authored scalar SELECT. Ratio numerators and
denominators are independently executable SELECTs. Queries bind `:as_of_date`
to frozen configuration; none are supplied by a model or a user.

| ID | Display name | Unit | Definition / grain rule |
|---|---|---|---|
| order_lines | Order lines | count | COUNT(*) on order_items, not units and not orders. |
| orders | Orders | count | COUNT(DISTINCT order_id); never COUNT(*) over joined lines. |
| units_sold | Units sold | count | SUM(quantity), not line count; includes sold units subsequently refunded. |
| gross_revenue | Gross revenue | USD | Sum quantity*unit_price once per line; excludes shipping and tax; no order amounts joined into a sum. |
| net_revenue | Net revenue | USD | commerce_lines allocates each order discount once and preaggregates refunds to one row per line. Tax and shipping excluded. |
| aov | Average order value | USD | Aggregate net revenue before division by distinct eligible orders; never sum order-level amounts across lines. |
| gross_margin | Gross margin | USD | Absolute USD margin, not margin percentage. Returned goods have no COGS recovery; costs count once per line. |
| discount_rate | Discount rate | ratio | Ratio of sums; order discount is allocated once per order, not repeated for each joined line. |
| cancellation_rate | Cancellation rate | ratio | Pending orders remain in denominator. Compute at order grain without joining lines. |
| return_rate | Return rate | ratio | Line-based, not unit-based or order-based. Any positive partial refund counts as one returned line; preaggregate refunds. |
| new_customers | New customers | count | New means signup, not first purchase; no order join required. |
| repeat_purchase_rate | Repeat purchase rate | ratio | Group orders by customer first; distinct customers form denominator. Recompute for each period/group; do not average rates. |
| conversion_rate | Conversion rate | ratio | Converted means submitted an order, including later cancellations; one order per converted session. No sessions-to-orders fan-out. |
| discounts | Discounts | USD | Sum line discounts and allocated order discounts only; never sum raw orders.order_discount across lines. |
| refunds | Refunds | USD | Returns aggregate to line grain before joining. Snapshot only includes refunds before AS_OF_DATE; no shipping or tax refunds. |

## Dimensions

- **order_region**: Shipping/order region captured on the order; may differ from customer region. Available at: order_items, orders.
- **customer_region**: Customer profile region; unqualified region requires clarification. Available at: order_items, orders, customers, sessions.
- **category**: Purchased product category at line grain. Available at: order_items.
- **brand**: Purchased product brand at line grain. Available at: order_items.
- **device**: Device on the attributed session. Available at: order_items, orders, sessions.
- **traffic_source**: Traffic source on the attributed session. Available at: order_items, orders, sessions.
- **age_group**: Synthetic customer age band. Available at: order_items, orders, customers, sessions.
- **month**: Calendar YYYY-MM using the metric base date; not a join to a calendar table. Available at: order_items, orders, customers, sessions.
- **quarter**: Calendar YYYY-Q1 through YYYY-Q4 using the metric base date. Available at: order_items, orders, customers, sessions.

Month and quarter are allowed for every metric, using order_date for orders and
lines, session_date for sessions, and signup_date for customers. Grouped request
compilation and time transformations are implemented in app/sql/compiler.py;
source columns and safe paths are validated before use. Month means YYYY-MM and
quarter means YYYY-Qn.

## Deliberate ambiguities

- **revenue** -> outcome `clarify`: Ask: Do you mean gross revenue before discounts/refunds, or net revenue after both? Never select a default.
- **region** -> outcome `clarify`: Ask: Do you mean order/shipping region or customer profile region? Never infer a default from metric availability.

Neither ambiguous term is a standalone metric synonym. The service enforces
these clarification rules before model selection; there is no default.

## Assumptions

- Recognized sales use completed and returned orders; pending and cancelled
  orders are excluded from sales, margin, AOV and sales-based rates.
- Orders and order_lines count all statuses. Units sold count recognized sale
  quantities without inferring returned units from cash refunds.
- Net revenue subtracts line discounts, allocated order discounts and merchandise
  refunds. Tax and shipping are excluded. Gross margin is absolute USD net revenue
  minus sold-unit cost, with no returned-stock COGS recovery.
- Return rate uses refunded lines / recognized lines. Cancellation rate uses
  cancelled orders / all submitted orders, including pending.
- Conversion uses submitted orders / sessions, regardless of later cancellation.
  All sessions are identified customers; at most one order per session.
- New customers means signups. Repeat purchase rate uses customers with >=2
  recognized orders / customers with >=1 within the requested order-date period.
  Recompute ratios after grouping; never average ratios. Distinct-customer counts
  and rates are not additive across groups.
- Refunds belong to original order-date periods. This is a frozen snapshot, not
  historical reconstruction: commerce_lines includes all seeded refunds, each
  before AS_OF_DATE. Arbitrary earlier as-of refund snapshots would require a
  parameterized refund aggregation in the future compiler.
- Zero denominators yield NULL. Count and sum formulas yield zero for empty
  inputs. Future service orchestration must decide answer versus empty_result.

## Validation

Tests resolve every formula and numerator/denominator against SQLite, exercise
all allowed metric-dimension pairs, compare independent Python financial totals,
reconcile category splits and reject bad metadata, unsafe SQL and reverse joins.
No locked evaluation data or LLM is used.
