# Text-to-SQL Analytics Assistant

Ask business questions in **English or Hinglish** ("Pichhle mahine ki sales kitni thi?") and get the **generated SQL, a plain-language answer and a chart**. Built with Streamlit, Google Gemini, SQLite and Plotly.

## Features
- Natural language to SQL with Gemini (JSON output: SQL + chart type + explanation)
- **SQL guard**: only a single read-only SELECT is allowed, comments and DDL/DML are blocked
- **Read-only** in-memory SQLite database (`PRAGMA query_only`)
- **Self-repair**: if the SQL fails, the error is sent back to the model for one corrected attempt
- Auto charts (line, bar, pie, metric card) with INR formatting (Lakhs / Crores)
- Multi-turn context for follow-ups ("now show it by region")
- Built-in sample sales database (3,000 orders, last 12 months) + **upload your own CSV**
- **Demo mode** without an API key (template-based, English + Hinglish)
- Download any result as CSV, view the SQL behind every answer

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```
Optional: paste a Gemini key (free at https://aistudio.google.com) in the sidebar, or set `GEMINI_API_KEY`.

## Deploy (Streamlit Community Cloud)
1. Push this folder to a **public** GitHub repo (files at the repo root, `modules/` as a folder).
2. share.streamlit.io -> Create app -> pick repo, branch `main`, file `app.py`.
3. Optional secret: `GEMINI_API_KEY = "your-key"` (leave it out for a public demo).

## Run tests
```bash
python tests/test_core.py
```

## Project structure
```
app.py                 Streamlit UI (chat, sidebar, rendering)
modules/db.py          Sample DB, CSV loader, schema helpers, read-only connection
modules/sql_guard.py   SQL safety validation
modules/nl2sql.py      Gemini engine + demo rule engine + summaries
modules/charts.py      Plotly chart builder
tests/test_core.py     Unit tests for guard, DB, engine
REPORT.md              Project report (abstract, architecture, evaluation, limitations)
```

## Example questions (sample DB)
- Pichhle mahine ki sales kitni thi?
- Show monthly sales trend
- Top 5 products by revenue
- Sales by region / Revenue by category
- Top 10 customers by spending
- Order status breakdown
- Average order value by segment

> Note: AI-generated SQL can be wrong. Always check the displayed SQL before relying on a number.
