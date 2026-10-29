"""Database layer: sample sales database (SQLite, in-memory), CSV upload, schema helpers.

No external database is needed. Everything lives in memory for the session.
"""
import random
import re
import sqlite3
from datetime import date, timedelta
from typing import Dict, List

import pandas as pd

REGIONS: Dict[str, List[str]] = {
    "North": ["Delhi", "Jaipur", "Lucknow"],
    "South": ["Bengaluru", "Chennai", "Hyderabad"],
    "West": ["Mumbai", "Pune", "Ahmedabad"],
    "East": ["Kolkata", "Bhubaneswar", "Patna"],
}

PRODUCTS = [
    ("Laptop", "Electronics", 55000), ("Smartphone", "Electronics", 22000),
    ("Headphones", "Electronics", 3500), ("Smart Watch", "Electronics", 6500),
    ("Office Chair", "Furniture", 8500), ("Study Desk", "Furniture", 12000),
    ("Bookshelf", "Furniture", 6000), ("Running Shoes", "Fashion", 3200),
    ("Backpack", "Fashion", 1800), ("Jacket", "Fashion", 4200),
    ("Mixer Grinder", "Home Appliances", 4500), ("Air Fryer", "Home Appliances", 7000),
    ("Water Purifier", "Home Appliances", 14000), ("Notebook Pack", "Stationery", 450),
    ("Fountain Pen", "Stationery", 900),
]

FIRST = ["Aarav", "Diya", "Rohan", "Ananya", "Vihaan", "Isha", "Kabir", "Meera", "Arjun", "Saanvi",
         "Rahul", "Priya", "Aditya", "Neha", "Karan", "Pooja", "Siddharth", "Kavya", "Manish", "Riya"]
LAST = ["Sharma", "Verma", "Patel", "Reddy", "Nair", "Gupta", "Singh", "Das", "Mehta", "Iyer"]

SCHEMA_DDL = """
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, city TEXT, region TEXT, segment TEXT);
CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT, category TEXT, unit_price REAL);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY, customer_id INTEGER, product_id INTEGER,
    order_date TEXT, quantity INTEGER, discount REAL, revenue REAL, status TEXT
);
"""

SCHEMA_NOTES = (
    "orders.order_date is ISO text 'YYYY-MM-DD'. orders.revenue = quantity * unit_price * (1 - discount) in INR. "
    "orders.status is one of Delivered, Returned, Cancelled. "
    "Sales / revenue means SUM(orders.revenue) over status = 'Delivered' unless the user says otherwise. "
    "customers.segment is one of Consumer, Corporate, Small Business."
)


def build_demo_db(seed: int = 42, n_orders: int = 3000) -> sqlite3.Connection:
    """Create a seeded in-memory sales database covering the last ~12 months."""
    rnd = random.Random(seed)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(SCHEMA_DDL)

    customers = []
    cid = 1
    for region, cities in REGIONS.items():
        for city in cities:
            for _ in range(6):
                name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
                customers.append((cid, name, city, region, rnd.choice(["Consumer", "Consumer", "Corporate", "Small Business"])))
                cid += 1
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", customers)
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)",
                     [(i + 1, n, c, p) for i, (n, c, p) in enumerate(PRODUCTS)])

    today = date.today()
    start = today - timedelta(days=365)
    orders = []
    for oid in range(1, n_orders + 1):
        d = start + timedelta(days=rnd.randint(0, 365))
        # Festive-season uplift (Oct-Nov) and growth through the year
        if d.month in (10, 11) and rnd.random() < 0.35:
            d = d.replace(day=min(d.day, 28))
        pid = rnd.choices(range(1, len(PRODUCTS) + 1),
                          weights=[3, 6, 8, 5, 3, 2, 2, 7, 8, 5, 4, 3, 2, 10, 9])[0]
        price = PRODUCTS[pid - 1][2]
        qty = rnd.choices([1, 2, 3, 4], weights=[70, 20, 7, 3])[0]
        disc = rnd.choice([0, 0, 0.05, 0.1, 0.15])
        status = rnd.choices(["Delivered", "Returned", "Cancelled"], weights=[85, 8, 7])[0]
        orders.append((oid, rnd.randint(1, len(customers)), pid, d.isoformat(), qty, disc,
                       round(qty * price * (1 - disc), 2), status))
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", orders)
    conn.commit()
    conn.execute("PRAGMA query_only = ON")  # read-only for all later queries
    return conn


def _clean_name(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", str(name).strip()).strip("_").lower()
    return name or "col"


def build_db_from_csv(df: pd.DataFrame, table: str = "uploaded_data") -> sqlite3.Connection:
    """Load an uploaded DataFrame into an in-memory SQLite table."""
    if df.empty:
        raise ValueError("The uploaded CSV is empty.")
    df = df.copy()
    cols, seen = [], {}
    for c in df.columns:
        base = _clean_name(c)
        seen[base] = seen.get(base, 0) + 1
        cols.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    df.columns = cols
    for c in df.columns:  # store dates as ISO text so strftime() works
        if df[c].dtype == object:
            parsed = pd.to_datetime(df[c], errors="coerce")
            if parsed.notna().mean() > 0.9:
                df[c] = parsed.dt.strftime("%Y-%m-%d")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    df.to_sql(table, conn, index=False)
    conn.commit()
    conn.execute("PRAGMA query_only = ON")
    return conn


def get_schema_text(conn: sqlite3.Connection, sample_rows: int = 2) -> str:
    """Human/LLM readable schema with a few sample rows per table."""
    parts = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for t in tables:
        info = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
        cols = ", ".join(f"{c[1]} {c[2] or 'TEXT'}" for c in info)
        parts.append(f"TABLE {t} ({cols})")
        rows = conn.execute(f'SELECT * FROM "{t}" LIMIT {sample_rows}').fetchall()
        for r in rows:
            parts.append(f"  sample: {r}")
    return "\n".join(parts)


def get_tables(conn: sqlite3.Connection) -> Dict[str, List[str]]:
    out = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        out[t] = [c[1] for c in conn.execute(f'PRAGMA table_info("{t}")')]
    return out


def run_query(conn: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn)
