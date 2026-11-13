"""Warehouse constraints, reproducibility and explicit order/line grain checks."""

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.config import AS_OF_DATE, START_DATE
from app.db.seed import TABLES, create_warehouse


def test_volumes_and_constraints(db: sqlite3.Connection) -> None:
    """Check all requested volumes and FK integrity, not just joinable sample rows."""
    counts = {t:db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    assert counts == dict(customers=160,products=72,sessions=2400,orders=400,order_items=580,returns=43)
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert set(r[0] for r in db.execute("SELECT DISTINCT status FROM orders")) == {
        "completed","cancelled","returned","pending"}
    assert db.execute("SELECT COUNT(*) FROM order_items WHERE line_total != quantity*unit_price-line_discount").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM returns r JOIN order_items i USING(order_item_id) WHERE refund_amount>line_total").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM order_items WHERE quantity>1").fetchone()[0] > 0
    assert db.execute("SELECT SUM(line_discount) FROM order_items").fetchone()[0] > 0
    assert db.execute("SELECT SUM(order_discount) FROM orders").fetchone()[0] > 0


def test_session_order_correspondence(db: sqlite3.Connection) -> None:
    """Converted sessions and orders correspond one-to-one with matching customers."""
    assert db.execute("""SELECT COUNT(*) FROM sessions s LEFT JOIN orders o USING(session_id)
        WHERE (s.converted=1 AND o.order_id IS NULL)
        OR (s.converted=0 AND o.order_id IS NOT NULL)
        OR (s.customer_id != o.customer_id) OR (s.session_date != o.order_date)""").fetchone()[0] == 0
    assert db.execute("SELECT SUM(converted) FROM sessions").fetchone()[0] == 400
    assert db.execute("""SELECT COUNT(*) FROM orders o WHERE NOT EXISTS
        (SELECT 1 FROM order_items i WHERE i.order_id=o.order_id)""").fetchone()[0] == 0


def test_temporal_consistency_and_seasonality(db: sqlite3.Connection) -> None:
    """The entire 18-month window is represented and holiday traffic is elevated."""
    start,end = db.execute("SELECT MIN(order_date),MAX(order_date) FROM orders").fetchone()
    assert start == START_DATE.isoformat()
    assert end == "2026-10-31"
    assert db.execute("SELECT COUNT(DISTINCT substr(session_date,1,7)) FROM sessions").fetchone()[0] == 18
    assert db.execute("""SELECT COUNT(*) FROM sessions s JOIN customers c USING(customer_id)
        WHERE session_date<signup_date OR session_date>=?""",(AS_OF_DATE.isoformat(),)).fetchone()[0] == 0
    assert db.execute("""SELECT COUNT(*) FROM returns r JOIN order_items i USING(order_item_id)
        JOIN orders o USING(order_id) WHERE return_date<=order_date OR return_date>=?
        OR status!='returned'""",(AS_OF_DATE.isoformat(),)).fetchone()[0] == 0
    holiday = db.execute("SELECT COUNT(*) FROM sessions WHERE substr(session_date,6,2) IN ('11','12')").fetchone()[0]
    # Only 61 holiday days versus 488 other days in this window.
    assert holiday/61 > (2400-holiday)/488*1.5
    assert db.execute("SELECT COUNT(*) FROM orders o JOIN customers c USING(customer_id) WHERE o.region!=c.region").fetchone()[0] > 0


def test_allocation_and_line_view_grain(db: sqlite3.Connection) -> None:
    """Order discounts reconcile exactly in cents without duplicating line rows."""
    assert db.execute("SELECT COUNT(*),COUNT(DISTINCT order_item_id) FROM commerce_lines").fetchone()[:] == (580,580)
    assert not db.execute("""SELECT order_id FROM commerce_lines GROUP BY order_id
        HAVING SUM(allocated_order_discount)!=MAX(order_discount)""").fetchall()
    assert db.execute("""SELECT COUNT(*) FROM commerce_lines WHERE allocated_order_discount<0
        OR allocated_order_discount>line_total OR refund_cents>line_total-allocated_order_discount""").fetchone()[0] == 0
    assert db.execute("SELECT SUM(allocated_order_discount) FROM commerce_lines").fetchone()[0] == db.execute("SELECT SUM(order_discount) FROM orders").fetchone()[0]


def test_reproducible_seed_and_refuse_overwrite(warehouse: Path, tmp_path: Path) -> None:
    """Identical seeds generate identical schema and rows without replacing files."""
    duplicate = tmp_path / "duplicate.db"
    create_warehouse(duplicate)
    with closing(sqlite3.connect(warehouse)) as first, closing(sqlite3.connect(duplicate)) as second:
        assert list(first.iterdump()) == list(second.iterdump())
    with pytest.raises(FileExistsError):
        create_warehouse(duplicate)


@pytest.mark.parametrize("sql",[
    "UPDATE orders SET status='shipped' WHERE order_id=1",
    "UPDATE order_items SET line_total=line_total+1 WHERE order_item_id=1",
    "UPDATE returns SET refund_amount=999999999 WHERE return_id=1",
    "INSERT INTO returns VALUES(999,1,'2026-10-31',999999999,'invalid')",
    "UPDATE order_items SET order_id=999999 WHERE order_item_id=1",
    "UPDATE orders SET customer_id=999999 WHERE order_id=1",
])
def test_database_rejects_corruption(sql: str, warehouse: Path, tmp_path: Path) -> None:
    """Prove CHECK, FK and cross-table refund constraints reject actual writes."""
    copied = tmp_path / "writable.db"
    shutil.copyfile(warehouse,copied)
    with closing(sqlite3.connect(copied)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql)


def test_readonly_connection(db: sqlite3.Connection) -> None:
    """The application connection cannot mutate the warehouse."""
    with pytest.raises(sqlite3.OperationalError):
        db.execute("DELETE FROM orders")
