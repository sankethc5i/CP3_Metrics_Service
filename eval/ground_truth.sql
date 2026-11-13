-- Independent handwritten reference SQL. No compiler, catalog formulas or commerce_lines.
-- Dates are half-open. Monetary storage is integer cents. Allocate discounts BEFORE filters.
-- name: common
WITH order_sums AS (
 SELECT order_id, SUM(line_total) AS subtotal, MIN(order_item_id) AS first_line
 FROM order_items GROUP BY order_id
), floors AS (
 SELECT i.order_item_id, i.order_id,
        CASE WHEN s.subtotal=0 THEN 0 ELSE (o.order_discount*i.line_total)/s.subtotal END AS allocated_floor
 FROM order_items i JOIN orders o ON o.order_id=i.order_id JOIN order_sums s ON s.order_id=i.order_id
), floor_sums AS (
 SELECT order_id, SUM(allocated_floor) AS floor_sum FROM floors GROUP BY order_id
), facts AS (
 SELECT i.*, o.order_date, o.status, o.customer_id, o.region AS order_region,
        c.region AS customer_region, c.age_group, p.category, p.brand, p.unit_cost,
        s.device_type AS device, s.traffic_source,
        f.allocated_floor + CASE WHEN i.order_item_id=z.first_line THEN o.order_discount-fs.floor_sum ELSE 0 END AS allocated_discount,
        COALESCE((SELECT SUM(r.refund_amount) FROM returns r WHERE r.order_item_id=i.order_item_id),0) AS refunded,
        SUBSTR(o.order_date,1,7) AS month,
        SUBSTR(o.order_date,1,4)||'-Q'||CAST((CAST(SUBSTR(o.order_date,6,2) AS INTEGER)+2)/3 AS INTEGER) AS quarter
 FROM order_items i JOIN orders o ON o.order_id=i.order_id
 JOIN products p ON p.product_id=i.product_id JOIN customers c ON c.customer_id=o.customer_id
 JOIN sessions s ON s.session_id=o.session_id JOIN order_sums z ON z.order_id=i.order_id
 JOIN floors f ON f.order_item_id=i.order_item_id JOIN floor_sums fs ON fs.order_id=i.order_id
), scoped AS (
 SELECT * FROM facts WHERE order_date>=:start_date AND order_date<:end_date
 AND (:category IS NULL OR category=:category) AND (:brand IS NULL OR brand=:brand)
 AND (:order_region IS NULL OR order_region=:order_region)
 AND (:customer_region IS NULL OR customer_region=:customer_region)
 AND (:device IS NULL OR device=:device) AND (:traffic_source IS NULL OR traffic_source=:traffic_source)
 AND (:age_group IS NULL OR age_group=:age_group) AND (:status IS NULL OR status=:status)
 AND (:month IS NULL OR month=:month) AND (:quarter IS NULL OR quarter=:quarter)
), sales AS (SELECT * FROM scoped WHERE status IN ('completed','returned'))
-- name: sales
SELECT SUM(quantity*unit_price)/100.0 AS gross_revenue,
 SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue,
 SUM(quantity) AS units_sold, SUM(line_discount+allocated_discount)/100.0 AS discounts,
 SUM(refunded)/100.0 AS refunds,
 SUM(line_total-allocated_discount-refunded-quantity*unit_cost)/100.0 AS gross_margin,
 SUM(line_total-allocated_discount-refunded)/100.0/COUNT(DISTINCT order_id) AS aov,
 1.0*SUM(line_discount+allocated_discount)/NULLIF(SUM(quantity*unit_price),0) AS discount_rate,
 1.0*SUM(CASE WHEN refunded>0 THEN 1 ELSE 0 END)/COUNT(*) AS return_rate
FROM sales HAVING COUNT(*)>0;
-- name: lines
SELECT COUNT(*) AS order_lines FROM scoped HAVING COUNT(*)>0;
-- name: orders
SELECT COUNT(*) AS orders,
 1.0*SUM(status='cancelled')/COUNT(*) AS cancellation_rate
FROM orders WHERE order_date>=:start_date AND order_date<:end_date
AND (:status IS NULL OR status=:status) HAVING COUNT(*)>0;
-- name: repeat
SELECT 1.0*SUM(n>=2)/COUNT(*) AS repeat_purchase_rate FROM (
 SELECT customer_id, COUNT(*) AS n FROM orders
 WHERE status IN ('completed','returned') AND order_date>=:start_date AND order_date<:end_date
 GROUP BY customer_id
) HAVING COUNT(*)>0;
-- name: sessions
SELECT 1.0*SUM(converted)/COUNT(*) AS conversion_rate FROM sessions
WHERE session_date>=:start_date AND session_date<:end_date HAVING COUNT(*)>0;
-- name: customers
SELECT COUNT(*) AS new_customers FROM customers
WHERE signup_date>=:start_date AND signup_date<:end_date HAVING COUNT(*)>0;
-- name: category
SELECT category, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue,
 SUM(quantity*unit_price)/100.0 AS gross_revenue, SUM(quantity) AS units_sold
FROM sales GROUP BY category ORDER BY category;
-- name: brand
SELECT brand, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue,
 SUM(quantity*unit_price)/100.0 AS gross_revenue
FROM sales GROUP BY brand ORDER BY brand;
-- name: order_region
SELECT order_region, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY order_region ORDER BY order_region;
-- name: customer_region
SELECT customer_region, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY customer_region ORDER BY customer_region;
-- name: device
SELECT device, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY device ORDER BY device;
-- name: traffic_source
SELECT traffic_source, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY traffic_source ORDER BY traffic_source;
-- name: age_group
SELECT age_group, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY age_group ORDER BY age_group;
-- name: month
SELECT month, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue,
 SUM(quantity*unit_price)/100.0 AS gross_revenue FROM sales GROUP BY month ORDER BY month;
-- name: quarter
SELECT quarter, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY quarter ORDER BY quarter;
-- name: category_month
SELECT category, month, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY category, month ORDER BY category, month;
-- name: brand_quarter
SELECT brand, quarter, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY brand, quarter ORDER BY brand, quarter;
-- name: device_month
SELECT device, month, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY device, month ORDER BY device, month;
-- name: category_brand
SELECT category, brand, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY category, brand ORDER BY category, brand;
-- name: category_order_region
SELECT category, order_region, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY category, order_region ORDER BY category, order_region;
-- name: traffic_age
SELECT traffic_source, age_group, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY traffic_source, age_group ORDER BY traffic_source, age_group;
-- name: customer_region_month
SELECT customer_region, month, SUM(line_total-allocated_discount-refunded)/100.0 AS net_revenue
FROM sales GROUP BY customer_region, month ORDER BY customer_region, month;
