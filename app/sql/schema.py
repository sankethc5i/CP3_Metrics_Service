"""A reviewed SQL column allow-list independent of model input and DB introspection."""

SCHEMA: dict[str,dict[str,str]] = {
    "customers":{c:"TEXT" for c in "customer_id customer_name age_group region city signup_date".split()},
    "products":{c:"TEXT" for c in "product_id product_name category brand unit_price unit_cost".split()},
    "sessions":{c:"TEXT" for c in "session_id customer_id session_date traffic_source device_type converted".split()},
    "orders":{c:"TEXT" for c in "order_id customer_id session_id order_date status region shipping_cost tax order_discount".split()},
    "order_items":{c:"TEXT" for c in "order_item_id order_id product_id quantity unit_price line_discount line_total".split()},
    "returns":{c:"TEXT" for c in "return_id order_item_id return_date refund_amount reason".split()},
    "commerce_lines":{c:"TEXT" for c in ("order_item_id order_id product_id quantity unit_price line_discount line_total "
        "status order_date customer_id session_id order_discount cost_per_unit refund_cents order_subtotal line_rank floor_discount allocated_order_discount").split()},
}
