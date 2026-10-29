"""Natural language to SQL engine.

Live mode  : Google Gemini generates SQL + chart spec as JSON (with one automatic self-repair retry).
Demo mode  : rule-based templates (English + Hinglish keywords) over the sample sales database.
Every query, in both modes, passes through sql_guard.validate_sql() and runs on a read-only connection.
"""
import json
import re
import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

from . import db
from .sql_guard import UnsafeSQLError, validate_sql

MODEL_CHOICES = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
DEFAULT_MODEL = MODEL_CHOICES[0]

EXAMPLES = [
    "Pichhle mahine ki sales kitni thi?",
    "Show monthly sales trend",
    "Top 5 products by revenue",
    "Sales by region",
    "Revenue by category",
    "Top 10 customers by spending",
    "Order status breakdown",
    "Average order value by segment",
]

SYSTEM_PROMPT = """You are a senior data analyst who converts business questions into SQLite SQL.

DATABASE SCHEMA
{schema}

NOTES
{notes}
Today's date is {today}. Use SQLite date functions (date('now'), strftime, 'start of month') for relative dates.

RULES
- Output a single read-only SELECT (or WITH ... SELECT) statement. Never modify data.
- Use only tables and columns that exist in the schema above.
- Give columns short readable aliases (e.g. month, sales, category).
- Round money to 2 decimals. Limit "top N" questions to N rows (default 10).
- The question may be in English, Hindi or Hinglish. Answer in the same language style.

Respond with ONLY valid JSON (no markdown fences):
{{
  "sql": "SELECT ...",
  "chart": {{"type": "line | bar | pie | table | metric", "x": "column for x axis or labels", "y": "numeric column", "title": "short title"}},
  "explanation": "one sentence describing what the query computes"
}}"""


# ------------------------------------------------------------------ helpers
def parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise ValueError("Model response was not valid JSON.")


def format_inr(amount: float) -> str:
    amount = float(amount)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1e7:
        return f"{sign}₹{amount / 1e7:,.2f} Cr"
    if amount >= 1e5:
        return f"{sign}₹{amount / 1e5:,.2f} L"
    return f"{sign}₹{amount:,.0f}"


MONEY_HINTS = ("sales", "revenue", "amount", "spend", "spent", "price", "value", "total", "cost", "profit")


def is_money_col(name: str) -> bool:
    n = str(name).lower()
    return any(h in n for h in MONEY_HINTS) and not any(x in n for x in ("count", "qty", "quantity", "orders"))


def infer_chart(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """Pick a sensible chart when the model/template did not specify one."""
    if df.empty:
        return {"type": "table", "x": None, "y": None, "title": ""}
    if df.shape == (1, 1):
        return {"type": "metric", "x": None, "y": df.columns[0], "title": ""}
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    non = [c for c in df.columns if c not in num]
    if not num:
        return {"type": "table", "x": None, "y": None, "title": ""}
    x = non[0] if non else df.columns[0]
    y = num[-1] if num[-1] != x else num[0]
    looks_time = bool(re.search(r"(date|day|month|year|week|time)", str(x), re.I))
    return {"type": "line" if looks_time else "bar", "x": x, "y": y, "title": ""}


def summarize(df: pd.DataFrame, question: str = "") -> str:
    """Plain-language one-line answer generated from the result table."""
    if df.empty:
        return "The query ran successfully but returned no rows."
    if df.shape == (1, 1):
        col, val = df.columns[0], df.iloc[0, 0]
        if isinstance(val, (int, float)) and is_money_col(col):
            return f"{col.replace('_', ' ').title()}: **{format_inr(val)}**"
        return f"{col.replace('_', ' ').title()}: **{val}**"
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not num:
        return f"Found {len(df)} rows."
    y = num[-1]
    label = next((c for c in df.columns if c not in num), df.columns[0])
    fmt = format_inr if is_money_col(y) else (lambda v: f"{v:,.2f}".rstrip("0").rstrip("."))
    top = df.loc[df[y].idxmax()]
    msg = f"{len(df)} rows. Highest **{y.replace('_', ' ')}**: **{top[label]}** ({fmt(top[y])})."
    if is_money_col(y) and len(df) > 1 and not re.search(r"avg|average|mean", y, re.I):
        msg += f" Total across rows: **{format_inr(df[y].sum())}**."
    return msg


# ------------------------------------------------------------------ demo (rule based)
_REV = "SUM(o.revenue)"
_DELIV = "o.status = 'Delivered'"


def _top_n(q: str, default: int = 5) -> int:
    m = re.search(r"\b(?:top|best|first)\s*(\d{1,2})\b", q) or re.search(r"\b(\d{1,2})\s*(?:best|top)\b", q)
    return max(1, min(int(m.group(1)), 50)) if m else default


def demo_generate(question: str) -> Dict[str, Any]:
    """Keyword based NL->SQL for the sample sales database (English + Hinglish)."""
    q = question.lower()
    has = lambda *words: any(w in q for w in words)  # noqa: E731

    last_month = has("last month", "previous month", "pichhle mahine", "pichle mahine", "pichhle month", "pichle month")
    this_month = has("this month", "is mahine", "current month", "iss mahine")
    sales_word = has("sale", "sales", "revenue", "bikri", "kamai", "income", "turnover")

    if (last_month or this_month) and not has("top", "category", "region", "customer", "product"):
        if last_month:
            cond = "o.order_date >= date('now','start of month','-1 month') AND o.order_date < date('now','start of month')"
            label = "last month"
        else:
            cond = "o.order_date >= date('now','start of month')"
            label = "this month"
        if has("total", "kitni", "kitna", "how much", "kul") and not has("daily", "day", "trend", "roz"):
            return {
                "sql": f"SELECT ROUND({_REV},2) AS total_sales FROM orders o WHERE {_DELIV} AND {cond}",
                "chart": {"type": "metric", "x": None, "y": "total_sales", "title": f"Total sales {label}"},
                "explanation": f"Total delivered revenue for {label}.",
            }
        return {
            "sql": f"SELECT o.order_date AS day, ROUND({_REV},2) AS sales FROM orders o WHERE {_DELIV} AND {cond} "
                   f"GROUP BY o.order_date ORDER BY o.order_date",
            "chart": {"type": "line", "x": "day", "y": "sales", "title": f"Daily sales {label}"},
            "explanation": f"Daily delivered revenue for {label}.",
        }

    if has("segment") and not has("average order", "aov", "avg order", "average sale", "ausat"):
        return {
            "sql": f"SELECT c.segment AS segment, ROUND({_REV},2) AS sales FROM orders o "
                   f"JOIN customers c ON c.customer_id = o.customer_id WHERE {_DELIV} GROUP BY c.segment "
                   "ORDER BY sales DESC",
            "chart": {"type": "pie", "x": "segment", "y": "sales", "title": "Sales by customer segment"},
            "explanation": "Delivered revenue by customer segment.",
        }

    if has("customer", "grahak", "client", "buyer"):
        n = _top_n(q, 10)
        return {
            "sql": f"SELECT c.name AS customer, ROUND({_REV},2) AS total_spent FROM orders o "
                   f"JOIN customers c ON c.customer_id = o.customer_id WHERE {_DELIV} "
                   f"GROUP BY c.customer_id ORDER BY total_spent DESC LIMIT {n}",
            "chart": {"type": "bar", "x": "customer", "y": "total_spent", "title": f"Top {n} customers by spending"},
            "explanation": f"Top {n} customers ranked by delivered revenue.",
        }

    if has("status", "return", "cancel", "delivered", "breakdown"):
        return {
            "sql": "SELECT status, COUNT(*) AS orders FROM orders GROUP BY status ORDER BY orders DESC",
            "chart": {"type": "pie", "x": "status", "y": "orders", "title": "Orders by status"},
            "explanation": "Number of orders in each fulfilment status.",
        }

    if has("average order", "aov", "avg order", "average sale", "ausat"):
        if has("segment"):
            return {
                "sql": "SELECT c.segment AS segment, ROUND(AVG(o.revenue),2) AS avg_order_value FROM orders o "
                       f"JOIN customers c ON c.customer_id = o.customer_id WHERE {_DELIV} GROUP BY c.segment "
                       "ORDER BY avg_order_value DESC",
                "chart": {"type": "bar", "x": "segment", "y": "avg_order_value", "title": "Average order value by segment"},
                "explanation": "Average delivered order value per customer segment.",
            }
        return {
            "sql": "SELECT p.category AS category, ROUND(AVG(o.revenue),2) AS avg_order_value FROM orders o "
                   f"JOIN products p ON p.product_id = o.product_id WHERE {_DELIV} GROUP BY p.category "
                   "ORDER BY avg_order_value DESC",
            "chart": {"type": "bar", "x": "category", "y": "avg_order_value", "title": "Average order value by category"},
            "explanation": "Average delivered order value per product category.",
        }

    if has("category", "categories", "shreni"):
        return {
            "sql": f"SELECT p.category AS category, ROUND({_REV},2) AS sales FROM orders o "
                   f"JOIN products p ON p.product_id = o.product_id WHERE {_DELIV} GROUP BY p.category "
                   "ORDER BY sales DESC",
            "chart": {"type": "bar", "x": "category", "y": "sales", "title": "Revenue by category"},
            "explanation": "Delivered revenue per product category.",
        }

    if has("product", "item", "saman", "cheez"):
        n = _top_n(q, 5)
        return {
            "sql": f"SELECT p.name AS product, ROUND({_REV},2) AS sales FROM orders o "
                   f"JOIN products p ON p.product_id = o.product_id WHERE {_DELIV} "
                   f"GROUP BY p.product_id ORDER BY sales DESC LIMIT {n}",
            "chart": {"type": "bar", "x": "product", "y": "sales", "title": f"Top {n} products by revenue"},
            "explanation": f"Top {n} products ranked by delivered revenue.",
        }

    if has("city", "cities", "shehar", "sheher"):
        n = _top_n(q, 10)
        return {
            "sql": f"SELECT c.city AS city, ROUND({_REV},2) AS sales FROM orders o "
                   f"JOIN customers c ON c.customer_id = o.customer_id WHERE {_DELIV} "
                   f"GROUP BY c.city ORDER BY sales DESC LIMIT {n}",
            "chart": {"type": "bar", "x": "city", "y": "sales", "title": "Sales by city"},
            "explanation": "Delivered revenue per city.",
        }

    if has("region", "zone", "area", "kshetra"):
        return {
            "sql": f"SELECT c.region AS region, ROUND({_REV},2) AS sales FROM orders o "
                   f"JOIN customers c ON c.customer_id = o.customer_id WHERE {_DELIV} GROUP BY c.region "
                   "ORDER BY sales DESC",
            "chart": {"type": "pie", "x": "region", "y": "sales", "title": "Sales by region"},
            "explanation": "Delivered revenue per region.",
        }

    if has("discount"):
        return {
            "sql": "SELECT CAST(ROUND(discount*100) AS INTEGER) || '%' AS discount, COUNT(*) AS orders, ROUND(SUM(revenue),2) AS sales "
                   "FROM orders WHERE status = 'Delivered' GROUP BY discount ORDER BY discount",
            "chart": {"type": "bar", "x": "discount", "y": "sales", "title": "Sales by discount level"},
            "explanation": "Orders and revenue grouped by discount percentage.",
        }

    if has("month", "mahine", "mahina", "trend", "monthly", "timeline", "growth", "over time"):
        return {
            "sql": f"SELECT strftime('%Y-%m', o.order_date) AS month, ROUND({_REV},2) AS sales FROM orders o "
                   f"WHERE {_DELIV} GROUP BY month ORDER BY month",
            "chart": {"type": "line", "x": "month", "y": "sales", "title": "Monthly sales trend"},
            "explanation": "Delivered revenue per calendar month.",
        }

    if has("year", "saal", "this year", "total", "overall", "kul") and sales_word:
        return {
            "sql": f"SELECT ROUND({_REV},2) AS total_sales FROM orders o WHERE {_DELIV}",
            "chart": {"type": "metric", "x": None, "y": "total_sales", "title": "Total sales"},
            "explanation": "Total delivered revenue across all data.",
        }

    # Fallback: monthly trend
    return {
        "sql": f"SELECT strftime('%Y-%m', o.order_date) AS month, ROUND({_REV},2) AS sales FROM orders o "
               f"WHERE {_DELIV} GROUP BY month ORDER BY month",
        "chart": {"type": "line", "x": "month", "y": "sales", "title": "Monthly sales trend"},
        "explanation": "Demo mode could not match your question to a template, so the monthly sales trend is shown. "
                       "Add a Gemini API key for free-form questions.",
        "fallback": True,
    }


# ------------------------------------------------------------------ live (Gemini)
class Text2SQLEngine:
    def __init__(self, api_key: Optional[str], model_name: str = DEFAULT_MODEL):
        self.api_key = (api_key or "").strip()
        self.model_name = model_name

    @property
    def demo_mode(self) -> bool:
        return not self.api_key

    def _model(self):
        import google.generativeai as genai  # lazy import
        genai.configure(api_key=self.api_key)
        return genai.GenerativeModel(self.model_name)

    def _llm_generate(self, conn: sqlite3.Connection, question: str, history: List[Dict],
                      is_demo_db: bool, error_hint: str = "", prev_sql: str = "") -> Dict[str, Any]:
        notes = db.SCHEMA_NOTES if is_demo_db else "Treat the table as an uploaded dataset; infer meaning from column names and sample rows."
        prompt = SYSTEM_PROMPT.format(schema=db.get_schema_text(conn), notes=notes, today=date.today().isoformat())
        ctx = ""
        recent = [h for h in history if h.get("sql")][-3:]
        if recent:
            ctx = "\nPREVIOUS QUESTIONS (for follow-ups like 'now by region'):\n" + "\n".join(
                f"Q: {h['question']}\nSQL: {h['sql']}" for h in recent)
        user = f"{ctx}\n\nQUESTION: {question}"
        if error_hint:
            user += f"\n\nYour previous SQL failed.\nSQL: {prev_sql}\nError: {error_hint}\nReturn a corrected JSON response."
        resp = self._model().generate_content(
            prompt + user, generation_config={"temperature": 0.1, "response_mime_type": "application/json"})
        return parse_json(resp.text)

    def answer(self, conn: sqlite3.Connection, question: str, history: Optional[List[Dict]] = None,
               is_demo_db: bool = True) -> Dict[str, Any]:
        """Return {sql, chart, explanation, df, summary, mode}. Raises on unrecoverable errors."""
        history = history or []
        question = (question or "").strip()
        if not question:
            raise ValueError("Please type a question.")

        if self.demo_mode:
            if not is_demo_db:
                raise ValueError("Demo mode only works with the built-in sample database. "
                                 "Add a Gemini API key to query your uploaded CSV.")
            spec = demo_generate(question)
            safe = validate_sql(spec["sql"])
            df = db.run_query(conn, safe)
            mode = "demo"
        else:
            spec = self._llm_generate(conn, question, history, is_demo_db)
            try:
                safe = validate_sql(spec.get("sql", ""))
                df = db.run_query(conn, safe)
            except UnsafeSQLError:
                raise
            except Exception as exc:  # SQL error: one self-repair attempt
                spec = self._llm_generate(conn, question, history, is_demo_db,
                                          error_hint=str(exc), prev_sql=spec.get("sql", ""))
                safe = validate_sql(spec.get("sql", ""))
                df = db.run_query(conn, safe)
            mode = "gemini"

        chart = spec.get("chart") or {}
        cols = set(df.columns)
        if chart.get("type") not in ("line", "bar", "pie", "table", "metric") or \
                (chart.get("type") in ("line", "bar", "pie") and (chart.get("x") not in cols or chart.get("y") not in cols)):
            inferred = infer_chart(df)
            inferred["title"] = chart.get("title") or inferred["title"]
            chart = inferred
        return {
            "sql": validate_sql_display(spec["sql"]),
            "chart": chart,
            "explanation": spec.get("explanation", ""),
            "df": df,
            "summary": summarize(df, question),
            "mode": mode,
            "fallback": bool(spec.get("fallback")),
        }


def validate_sql_display(sql: str) -> str:
    """The SQL shown to the user (without the LIMIT wrapper)."""
    from .sql_guard import clean_sql
    return clean_sql(sql)
