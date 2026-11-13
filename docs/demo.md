# Eight-question offline demo

DEV oracle arguments; zero paid calls. Lookup retrieval; no model downloads.

| Question | Expected | Actual |
|---|---|---|
| What is our net revenue? | answer | answer |
| How many orders are recorded? | answer | answer |
| Net revenue by brand | answer | answer |
| What is our conversion rate? | answer | answer |
| Revenue in the previous quarter | clarify | clarify |
| Net revenue by region | clarify | clarify |
| Show customer acquisition cost | refuse | refuse |
| Net revenue for quarter 2020-Q2 | empty_result | empty_result |

## First question: real pipeline trace

```json
{
  "outcome": "answer",
  "value": 109969.63,
  "metric_definition": "Recognized merchandise gross less line discounts, allocated order discounts, and refunds. commerce_lines allocates each order discount once and preaggregates refunds to one row per line. Tax and shipping excluded. All dates are inclusive at period start and exclusive at period end. Global snapshot ends before AS_OF_DATE. Zero denominators produce NULL; currency is USD, stored in integer cents; ratios are fractions. The view commerce_lines preserves exactly one row per order_item_id.",
  "sql": "WITH line_snapshot AS MATERIALIZED (SELECT order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, status, order_date, customer_id, session_id, order_discount, cost_per_unit, refund_cents, order_subtotal, line_rank, floor_discount, allocated_order_discount FROM commerce_lines), scope AS MATERIALIZED (SELECT order_items.order_item_id AS scope_id FROM order_items JOIN orders ON order_items.order_id=orders.order_id WHERE orders.order_date >= :start_date AND orders.order_date < :end_date AND orders.status IN ('completed','returned')) SELECT net_revenue FROM (SELECT (SELECT (SELECT COALESCE(SUM(line_total - allocated_order_discount - refund_cents), 0) FROM (SELECT order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, status, order_date, customer_id, session_id, order_discount, cost_per_unit, refund_cents, order_subtotal, line_rank, floor_discount, allocated_order_discount FROM line_snapshot WHERE order_item_id IN (SELECT scope_id FROM scope)) AS commerce_lines WHERE status IN ('completed', 'returned') AND order_date < :as_of_date) / 100.0) AS net_revenue, (SELECT COUNT(*) FROM scope) AS __source_count) AS answer_rows WHERE __source_count > 0 AND net_revenue IS NOT NULL LIMIT 100",
  "trace_id": "c47803ec-9a2a-4b80-a585-831d61892e2f",
  "trace": [
    {
      "step": "question_received",
      "started_ms": 0.06930000017746352,
      "tokens": {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
      },
      "status": "ok",
      "question": "What is our net revenue?",
      "rag_mode": "lookup",
      "embedding_provider": "local",
      "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
      "latency_ms": 0.3797000026679598
    },
    {
      "step": "retrieval",
      "started_ms": 1.0021000016422477,
      "tokens": {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
      },
      "status": "ok",
      "candidates": [
        {
          "chunk": {
            "id": "metric:net_revenue",
            "kind": "metric",
            "text": "Net revenue\nRecognized merchandise gross less line discounts, allocated order discounts, and refunds.\nSynonyms: net sales, net merchandise revenue\nDimensions: order_region, customer_region, category, brand, device, traffic_source, age_group, month, quarter\nExamples: What is net revenue? Show net revenue last month.\nRules: commerce_lines allocates each order discount once and preaggregates refunds to one row per line. Tax and shipping excluded. All dates are inclusive at period start and exclusive at period end. Global snapshot ends before AS_OF_DATE. Zero denominators produce NULL; currency is USD, stored in integer cents; ratios are fractions. The view commerce_lines preserves exactly one row per order_item_id.",
            "metadata": {
              "metric_id": "net_revenue",
              "aliases": [
                "net revenue",
                "Net revenue",
                "net sales",
                "net merchandise revenue"
              ],
              "unit": "USD",
              "grain": "one order line",
              "examples": [
                "What is net revenue?",
                "Show net revenue last month."
              ]
            }
          },
          "score": 204,
          "ranks": {
            "lookup": 1
          },
          "scores": {
            "lookup": 204
          }
        },
        {
          "chunk": {
            "id": "metric:aov",
            "kind": "metric",
            "text": "Average order value\nNet recognized merchandise revenue per distinct eligible order.\nSynonyms: average order value, average basket value\nDimensions: order_region, customer_region, device, traffic_source, age_group, month, quarter\nExamples: What is average order value? Show average order value last month.\nRules: Aggregate net revenue before division by distinct eligible orders; never sum order-level amounts across lines. All dates are inclusive at period start and exclusive at period end. Global snapshot ends before AS_OF_DATE. Zero denominators produce NULL; currency is USD, stored in integer cents; ratios are fractions.",
            "metadata": {
              "metric_id": "aov",
              "aliases": [
                "aov",
                "Average order value",
                "average order value",
                "average basket value"
              ],
              "unit": "USD",
              "grain": "one order; numerator preaggregates lines",
              "examples": [
                "What is average order value?",
                "Show average order value last month."
              ]
            }
          },
          "score": 4,
          "ranks": {
            "lookup": 2
          },
          "scores": {
            "lookup": 4
          }
        },
        {
          "chunk": {
            "id": "metric:gross_margin",
            "kind": "metric",
            "text": "Gross margin\nNet merchandise revenue less historical cost of sold units.\nSynonyms: gross profit, merchandise margin\nDimensions: order_region, customer_region, category, brand, device, traffic_source, age_group, month, quarter\nExamples: What is gross margin? Show gross margin last month.\nRules: Absolute USD margin, not margin percentage. Returned goods have no COGS recovery; costs count once per line. All dates are inclusive at period start and exclusive at period end. Global snapshot ends before AS_OF_DATE. Zero denominators produce NULL; currency is USD, stored in integer cents; ratios are fractions. The view commerce_lines preserves exactly one row per order_item_id.",
            "metadata": {
              "metric_id": "gross_margin",
              "aliases": [
                "gross margin",
                "Gross margin",
                "gross profit",
                "merchandise margin"
              ],
              "unit": "USD",
              "grain": "one order line",
              "examples": [
                "What is gross margin?",
                "Show gross margin last month."
              ]
            }
          },
          "score": 4,
          "ranks": {
            "lookup": 3
          },
          "scores": {
            "lookup": 4
          }
        },
        {
          "chunk": {
            "id": "metric:discount_rate",
            "kind": "metric",
            "text": "Discount rate\nLine discounts plus allocated order discounts divided by gross merchandise revenue.\nSynonyms: discount percentage, merchandise discount rate\nDimensions: order_region, customer_region, category, brand, device, traffic_source, age_group, month, quarter\nExamples: What is discount rate? Show discount rate last month.\nRules: Ratio of sums; order discount is allocated once per order, not repeated for each joined line. All dates are inclusive at period start and exclusive at period end. Global snapshot ends before AS_OF_DATE. Zero denominators produce NULL; currency is USD, stored in integer cents; ratios are fractions. The view commerce_lines preserves exactly one row per order_item_id.",
            "metadata": {
              "metric_id": "discount_rate",
              "aliases": [
                "discount rate",
                "Discount rate",
                "discount percentage",
                "merchandise discount rate"
              ],
              "unit": "ratio",
              "grain": "one order line",
              "examples": [
                "What is discount rate?",
                "Show discount rate last month."
              ]
            }
          },
          "score": 3,
          "ranks": {
            "lookup": 4
          },
          "scores": {
            "lookup": 3
          }
        },
        {
          "chunk": {
            "id": "metric:gross_revenue",
            "kind": "metric",
            "text": "Gross revenue\nRecognized merchandise revenue before discounts and refunds.\nSynonyms: gross sales, gross merchandise revenue\nDimensions: order_region, customer_region, category, brand, device, traffic_source, age_group, month, quarter\nExamples: What is gross revenue? Show gross revenue last month.\nRules: Sum quantity*unit_price once per line; excludes shipping and tax; no order amounts joined into a sum. All dates are inclusive at period start and exclusive at period end. Global snapshot ends before AS_OF_DATE. Zero denominators produce NULL; currency is USD, stored in integer cents; ratios are fractions. The view commerce_lines preserves exactly one row per order_item_id.",
            "metadata": {
              "metric_id": "gross_revenue",
              "aliases": [
                "gross revenue",
                "Gross revenue",
                "gross sales",
                "gross merchandise revenue"
              ],
              "unit": "USD",
              "grain": "one order line",
              "examples": [
                "What is gross revenue?",
                "Show gross revenue last month."
              ]
            }
          },
          "score": 3,
          "ranks": {
            "lookup": 5
          },
          "scores": {
            "lookup": 3
          }
        },
        {
          "chunk": {
            "id": "ambiguity:revenue",
            "kind": "rule",
            "text": "Ask: Do you mean gross revenue before discounts/refunds, or net revenue after both? Never select a default.",
            "metadata": {
              "term": "revenue",
              "options": [
                "gross_revenue",
                "net_revenue"
              ],
              "outcome": "clarify"
            }
          },
          "score": 2,
          "ranks": {
            "lookup": 6
          },
          "scores": {
            "lookup": 2
          }
        }
      ],
      "top_metric": "net_revenue",
      "latency_ms": 1.3758999994024634
    },
    {
      "step": "function_call",
      "started_ms": 7.811400002537994,
      "tokens": {},
      "status": "ok",
      "source": "model",
      "function": "select_metric",
      "arguments": {
        "metric_id": "net_revenue",
        "dimensions": [],
        "filters": [],
        "time_range": {
          "start": null,
          "end": null,
          "relative": "all_time"
        },
        "grain": "total"
      },
      "latency_ms": 0.02559999848017469
    },
    {
      "step": "argument_validation",
      "started_ms": 8.360400002857205,
      "tokens": {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
      },
      "status": "ok",
      "validated": true,
      "latency_ms": 0.03399999695830047
    },
    {
      "step": "catalog_metric_check",
      "started_ms": 8.554300002288073,
      "tokens": {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
      },
      "status": "ok",
      "metric_id": "net_revenue",
      "latency_ms": 0.02099999983329326
    },
    {
      "step": "allow_list_validation",
      "started_ms": 8.795000001555309,
      "tokens": {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
      },
      "status": "ok",
      "start": "1900-01-01",
      "end": "2026-11-01",
      "dimensions": [],
      "grain": "total",
      "latency_ms": 0.03279999873484485
    },
    {
      "step": "sql_compile",
      "started_ms": 9.190100001433166,
      "tokens": {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
      },
      "status": "ok",
      "sql": "WITH line_snapshot AS MATERIALIZED (SELECT order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, status, order_date, customer_id, session_id, order_discount, cost_per_unit, refund_cents, order_subtotal, line_rank, floor_discount, allocated_order_discount FROM commerce_lines), scope AS MATERIALIZED (SELECT order_items.order_item_id AS scope_id FROM order_items JOIN orders ON order_items.order_id=orders.order_id WHERE orders.order_date >= :start_date AND orders.order_date < :end_date AND orders.status IN ('completed','returned')) SELECT net_revenue FROM (SELECT (SELECT (SELECT COALESCE(SUM(line_total - allocated_order_discount - refund_cents), 0) FROM (SELECT order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, status, order_date, customer_id, session_id, order_discount, cost_per_unit, refund_cents, order_subtotal, line_rank, floor_discount, allocated_order_discount FROM line_snapshot WHERE order_item_id IN (SELECT scope_id FROM scope)) AS commerce_lines WHERE status IN ('completed', 'returned') AND order_date < :as_of_date) / 100.0) AS net_revenue, (SELECT COUNT(*) FROM scope) AS __source_count) AS answer_rows WHERE __source_count > 0 AND net_revenue IS NOT NULL LIMIT 100",
      "parameters": {
        "start_date": "1900-01-01",
        "end_date": "2026-11-01",
        "as_of_date": "2026-11-01"
      },
      "latency_ms": 2.2241000006033573
    },
    {
      "step": "sql_validation",
      "started_ms": 11.960300002101576,
      "tokens": {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
      },
      "status": "ok",
      "validated": true,
      "latency_ms": 87.36710000084713
    },
    {
      "step": "db_execution",
      "started_ms": 99.52380000322592,
      "tokens": {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
      },
      "status": "ok",
      "row_count": 1,
      "row_limit": 100,
      "latency_ms": 29.032699996605515
    },
    {
      "step": "answer_generation",
      "started_ms": 128.7625000004482,
      "tokens": {},
      "status": "ok",
      "source": "model",
      "latency_ms": 0.08480000178678893
    }
  ]
}
```
