PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    customer_name TEXT NOT NULL,
    age_group TEXT NOT NULL CHECK(age_group IN ('18-24','25-34','35-44','45-54','55+')),
    region TEXT NOT NULL,
    city TEXT NOT NULL,
    signup_date TEXT NOT NULL
);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT NOT NULL,
    unit_price INTEGER NOT NULL CHECK(unit_price > 0),
    unit_cost INTEGER NOT NULL CHECK(unit_cost BETWEEN 0 AND unit_price)
);
CREATE TABLE sessions (
    session_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    session_date TEXT NOT NULL,
    traffic_source TEXT NOT NULL,
    device_type TEXT NOT NULL,
    converted INTEGER NOT NULL CHECK(converted IN (0,1)),
    UNIQUE(session_id, customer_id)
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    session_id INTEGER NOT NULL UNIQUE,
    order_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('completed','cancelled','returned','pending')),
    region TEXT NOT NULL,
    shipping_cost INTEGER NOT NULL CHECK(shipping_cost >= 0),
    tax INTEGER NOT NULL CHECK(tax >= 0),
    order_discount INTEGER NOT NULL CHECK(order_discount >= 0),
    FOREIGN KEY(session_id,customer_id) REFERENCES sessions(session_id,customer_id)
);
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price INTEGER NOT NULL CHECK(unit_price > 0),
    line_discount INTEGER NOT NULL CHECK(line_discount BETWEEN 0 AND quantity*unit_price),
    line_total INTEGER NOT NULL CHECK(line_total = quantity*unit_price-line_discount)
);
CREATE TABLE returns (
    return_id INTEGER PRIMARY KEY,
    order_item_id INTEGER NOT NULL UNIQUE REFERENCES order_items(order_item_id),
    return_date TEXT NOT NULL,
    refund_amount INTEGER NOT NULL CHECK(refund_amount > 0),
    reason TEXT NOT NULL
);
CREATE TRIGGER check_refund_insert BEFORE INSERT ON returns BEGIN
    SELECT CASE WHEN NEW.refund_amount > (
        SELECT line_total FROM order_items WHERE order_item_id=NEW.order_item_id
    ) THEN RAISE(ABORT, 'refund exceeds line_total') END;
END;
CREATE TRIGGER check_refund_update BEFORE UPDATE ON returns BEGIN
    SELECT CASE WHEN NEW.refund_amount > (
        SELECT line_total FROM order_items WHERE order_item_id=NEW.order_item_id
    ) THEN RAISE(ABORT, 'refund exceeds line_total') END;
END;
CREATE TRIGGER check_refunded_line_update BEFORE UPDATE OF line_total ON order_items BEGIN
    SELECT CASE WHEN NEW.line_total < COALESCE((
        SELECT refund_amount FROM returns WHERE order_item_id=OLD.order_item_id
    ),0) THEN RAISE(ABORT, 'line_total below refund') END;
END;
CREATE INDEX idx_customers_signup ON customers(signup_date);
CREATE INDEX idx_sessions_customer_date ON sessions(customer_id,session_date);
CREATE INDEX idx_sessions_date ON sessions(session_date);
CREATE INDEX idx_orders_customer_date ON orders(customer_id,order_date);
CREATE INDEX idx_orders_date_status ON orders(order_date,status);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
CREATE INDEX idx_returns_date ON returns(return_date);

-- One output row per line. Only many-to-one joins; refunds aggregate first.
CREATE VIEW commerce_lines AS
WITH refund_totals AS (
    SELECT order_item_id, SUM(refund_amount) AS refund_cents
    FROM returns GROUP BY order_item_id
), weighted AS (
    SELECT i.*, o.status, o.order_date, o.customer_id, o.session_id,
           o.order_discount,
           p.unit_cost AS cost_per_unit,
           COALESCE(r.refund_cents,0) AS refund_cents,
           SUM(i.line_total) OVER (PARTITION BY i.order_id) AS order_subtotal,
           ROW_NUMBER() OVER (PARTITION BY i.order_id ORDER BY i.order_item_id) AS line_rank
    FROM order_items i
    JOIN orders o ON o.order_id=i.order_id
    JOIN products p ON p.product_id=i.product_id
    LEFT JOIN refund_totals r ON r.order_item_id=i.order_item_id
), allocations AS (
    SELECT *, order_discount*line_total / NULLIF(order_subtotal,0) AS floor_discount
    FROM weighted
)
SELECT *, floor_discount + CASE WHEN line_rank=1 THEN
    order_discount-SUM(floor_discount) OVER (PARTITION BY order_id)
    ELSE 0 END AS allocated_order_discount
FROM allocations;
