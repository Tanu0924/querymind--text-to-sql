"""Core logic tests (no Streamlit/Gemini needed). Run: python tests/test_core.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from modules import db  # noqa: E402
from modules.nl2sql import EXAMPLES, Text2SQLEngine, format_inr  # noqa: E402
from modules.sql_guard import UnsafeSQLError, validate_sql  # noqa: E402


def test_guard():
    ok = ["SELECT * FROM orders", "select count(*) from orders;", "WITH a AS (SELECT 1) SELECT * FROM a"]
    for s in ok:
        assert validate_sql(s).startswith("SELECT * FROM (")
    bad = ["DROP TABLE orders", "SELECT 1; DELETE FROM orders", "UPDATE orders SET revenue=0",
           "SELECT * FROM orders -- hi", "PRAGMA table_info(orders)", "INSERT INTO orders VALUES (1)",
           "SELECT * FROM orders /* x */", "", "ATTACH DATABASE 'x' AS y"]
    for s in bad:
        try:
            validate_sql(s)
        except UnsafeSQLError:
            continue
        raise AssertionError(f"Guard failed to block: {s}")
    print("guard OK")


def test_readonly():
    conn = db.build_demo_db()
    try:
        conn.execute("DELETE FROM orders")
    except Exception:
        print("read-only OK")
        return
    raise AssertionError("DB is not read-only")


def test_examples_and_hinglish():
    conn = db.build_demo_db()
    eng = Text2SQLEngine("")
    qs = EXAMPLES + ["Is mahine ki total bikri?", "top 3 cities", "sales by customer segment",
                     "discount ka effect", "kul sales", "pichle mahine ka daily trend", "something random xyz"]
    for q in qs:
        r = eng.answer(conn, q)
        assert isinstance(r["df"], pd.DataFrame)
        print(f"  {q!r:45} -> {r['chart']['type']:6} rows={len(r['df']):3} | {r['summary'][:70]}")
    r = eng.answer(conn, "Pichhle mahine ki sales kitni thi?")
    assert r["chart"]["type"] == "metric" and r["df"].shape == (1, 1)
    r = eng.answer(conn, "Top 5 products by revenue")
    assert len(r["df"]) == 5
    print("examples OK")


def test_csv_upload():
    df = pd.DataFrame({"Order Date": ["2026-01-05", "2026-02-10"], "Amount (INR)": [100, 250]})
    conn = db.build_db_from_csv(df)
    out = db.run_query(conn, "SELECT strftime('%Y-%m', order_date) AS m, SUM(amount_inr) AS t FROM uploaded_data GROUP BY m")
    assert len(out) == 2
    print("csv OK")


def test_format():
    assert format_inr(12_50_000) == "₹12.50 L" and format_inr(3.2e7) == "₹3.20 Cr" and format_inr(5000) == "₹5,000"
    print("format OK")


if __name__ == "__main__":
    test_guard(); test_readonly(); test_examples_and_hinglish(); test_csv_upload(); test_format()
    print("ALL TESTS PASSED")
