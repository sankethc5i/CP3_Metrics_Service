"""Reproducible, synthetic-only warehouse generation with integer-cent money."""

import random
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

from app.config import AS_OF_DATE, SEED, START_DATE

TABLES = ("customers", "products", "sessions", "orders", "order_items", "returns")
REGIONS = ("North", "South", "East", "West")
CITIES = ("Northhaven", "Southport", "Eastford", "Westbridge")


def create_warehouse(path: Path, seed: int = SEED) -> dict[str, int]:
    """Create a new seeded warehouse; refuse to overwrite any existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids accidental replacement of an existing warehouse.
    with path.open("xb"):
        pass
    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)
    days = [START_DATE + timedelta(days=n) for n in range((AS_OF_DATE-START_DATE).days)]
    weights = [2.8 if d.month in (11,12) else 1.5 if d.month == 7 else 1.0 for d in days]
    customer_signups = [START_DATE + timedelta(days=rng.randrange(90)) for _ in range(160)]
    customer_signups[0] = START_DATE
    customer_regions = [rng.randrange(4) for _ in range(160)]
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        db.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", [
            (i+1, "Synthetic " + fake.name(), rng.choice(("18-24","25-34","35-44","45-54","55+")),
             REGIONS[customer_regions[i]], CITIES[customer_regions[i]], signup.isoformat())
            for i, signup in enumerate(customer_signups)
        ])
        products: dict[int, tuple[int, int]] = {}
        for i in range(1,73):
            price = rng.randrange(500,30001)
            cost = price*rng.randrange(35,71)//100
            products[i] = (price,cost)
            db.execute("INSERT INTO products VALUES (?,?,?,?,?,?)", (
                i, f"Synthetic {fake.word().title()} {i}",
                ("Electronics","Home","Apparel","Sports","Books","Beauty")[(i-1)%6],
                ("Cedar","Nimbus","Orbit","Maple")[(i-1)%4], price,cost))
        # Customer 1 can visit on every day, ensuring the full window is represented.
        session_rows: list[tuple[int, int, str, str, str, int]] = []
        for i in range(1,2401):
            day = days[0] if i == 1 else days[-1] if i == 2 else rng.choices(days,weights=weights,k=1)[0]
            eligible = [c+1 for c,s in enumerate(customer_signups) if s <= day]
            customer = rng.choice(eligible)
            session_rows.append((i,customer,day.isoformat(),
                rng.choice(("organic","paid_search","email","social","direct")),
                rng.choice(("mobile","desktop","tablet")),0))
        selected = sorted(rng.sample(range(2,2400),398)+[0,1], key=lambda n: (session_rows[n][2],n))
        chosen = set(selected)
        db.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?)", [
            (*row[:5],int(n in chosen)) for n,row in enumerate(session_rows)
        ])
        # Exactly 180 two-line and 220 one-line orders: 580 lines overall.
        two_lines = set(rng.sample(range(1,401),180))
        line_id = 0
        return_id = 0
        for order_id, position in enumerate(selected,1):
            session = session_rows[position]
            status = rng.choices(("completed","cancelled","returned","pending"), (76,10,9,5))[0]
            if session[2] > (AS_OF_DATE-timedelta(days=32)).isoformat() and status == "returned":
                status = "completed"
            order_lines: list[tuple[int, int, int, int, int, int, int]] = []
            for product in rng.sample(range(1,73),2 if order_id in two_lines else 1):
                line_id += 1
                price = products[product][0]
                quantity = rng.choices((1,2,3,4),(60,25,10,5))[0]
                discount = quantity*price*rng.choice((0,0,0,5,10,15,20))//100
                order_lines.append((line_id,order_id,product,quantity,price,discount,quantity*price-discount))
            subtotal = sum(row[-1] for row in order_lines)
            order_discount = subtotal*rng.choice((0,0,0,5,10))//100
            region = customer_regions[session[1]-1]
            if rng.random() < 0.18:
                region = (region+1)%4
            db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)", (
                order_id,session[1],session[0],session[2],status,REGIONS[region],
                rng.choice((0,399,599,999)),(subtotal-order_discount)*8//100,order_discount))
            db.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?,?)",order_lines)
            if status == "returned":
                line = rng.choice(order_lines)
                return_id += 1
                # Refund <= post-order-discount line proceeds, even under cent rounding.
                allocated_max = order_discount*line[-1]//subtotal + len(order_lines)
                refund = max(1,(line[-1]-allocated_max)*rng.choice((50,100))//100)
                returned = min(AS_OF_DATE-timedelta(days=1),
                    date.fromisoformat(session[2])+timedelta(days=rng.randrange(1,31)))
                db.execute("INSERT INTO returns VALUES (?,?,?,?,?)", (
                    return_id,line[0],returned.isoformat(),refund,
                    rng.choice(("damaged","wrong_size","changed_mind"))))
        db.commit()
        return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}
