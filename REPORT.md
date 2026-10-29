# Text-to-SQL Analytics Assistant: Project Report

**Domain:** Generative AI | Business Intelligence
**Course:** B.Tech CSE, 7th Semester
**Stack:** Python, Streamlit, Google Gemini, SQLite, Pandas, Plotly

## 1. Abstract
Business users often need answers from databases but cannot write SQL. This project presents a conversational analytics assistant that converts questions written in English or Hinglish into safe SQL queries using a large language model (Google Gemini), executes them on a read-only database, and presents results as natural-language summaries and interactive charts. A multi-layer safety design (prompt rules, SQL validation, read-only database) prevents data modification, and a self-repair loop improves reliability when generated SQL fails.

## 2. Problem Statement
- Data teams are a bottleneck for simple recurring questions ("last month's sales?").
- Non-technical users cannot write SQL; dashboards are rigid.
- Naive LLM-to-SQL systems risk destructive queries, hallucinated columns and wrong answers.

## 3. Objectives
1. Convert natural-language questions (including Hinglish) to correct SQLite SQL.
2. Guarantee read-only, single-statement execution.
3. Auto-select an appropriate chart and give a plain-language answer.
4. Support follow-up questions and user-uploaded CSV data.
5. Work with zero external database and deploy in one click.

## 4. System Architecture
```
User question ──► Prompt builder (schema + sample rows + notes + today's date + recent history)
                         │
                         ▼
                  Gemini (JSON: sql, chart spec, explanation)
                         │
                         ▼
                  SQL Guard (single SELECT/WITH, no comments, no DDL/DML, row limit)
                         │
                         ▼
              Read-only in-memory SQLite  ──error──► Self-repair (error sent to LLM, 1 retry)
                         │
                         ▼
        DataFrame ──► Chart selector (line/bar/pie/metric) + summary ──► Streamlit UI
```
Demo mode replaces the Gemini step with a keyword template engine so the app works without an API key.

## 5. Modules
| Module | Responsibility |
|---|---|
| `db.py` | Seeded sample sales DB (customers, products, orders), CSV to SQLite loader, schema text, read-only connection |
| `nl2sql.py` | Prompt construction, Gemini call, JSON parsing, self-repair, demo templates, result summaries |
| `sql_guard.py` | Validates and wraps SQL: only one SELECT/WITH, blocks comments/keywords, applies `LIMIT 1000` |
| `charts.py` | Plotly figures and metric cards with INR formatting |
| `app.py` | Chat interface, sidebar, history, CSV upload, downloads |

## 6. Key Techniques
- **Schema-grounded prompting:** table definitions plus two sample rows per table reduce hallucinated columns.
- **Structured output:** the model returns JSON (`sql`, `chart`, `explanation`), parsed robustly.
- **Defence in depth:** (1) prompt forbids writes, (2) regex guard validates SQL, (3) `PRAGMA query_only=ON` makes the database physically read-only.
- **Self-correction:** on SQL execution error the message is fed back once for a fixed query.
- **Conversation memory:** the last three question/SQL pairs are included to resolve follow-ups.
- **Business semantics:** "sales" is defined as revenue of Delivered orders, stated in the prompt so answers are consistent.

## 7. Dataset
Synthetic sales data generated with a fixed seed (reproducible): 72 customers in 12 cities across 4 regions, 15 products in 5 categories, 3,000 orders over the last 12 months with discounts and Delivered/Returned/Cancelled statuses. Amounts are in INR. Users can instead upload any CSV.

## 8. Testing
`tests/test_core.py` verifies:
- Guard accepts valid SELECT/WITH and blocks DROP, DELETE, UPDATE, INSERT, PRAGMA, ATTACH, comments and multiple statements.
- Database rejects writes (read-only).
- All example questions, including Hinglish ones, return valid results and appropriate chart types.
- CSV upload creates a queryable table with normalised column names and ISO dates.
- INR formatting (Lakhs/Crores).

## 9. Results
All sample questions run end-to-end. Example: *"Pichhle mahine ki sales kitni thi?"* produces `SELECT ROUND(SUM(o.revenue),2) ... WHERE status='Delivered' AND order_date within previous month`, displayed as a metric card in Lakhs.
(Add screenshots of your running app here.)

## 10. Limitations
- LLM-generated SQL can be incorrect on ambiguous questions; the SQL is always shown for verification.
- Demo mode only covers a fixed set of templates.
- SQLite dialect only; very large databases are not supported (in-memory design).
- Uploaded CSV is analysed as a single table, no joins across files.
- Gemini free-tier rate limits apply in live mode.

## 11. Future Scope
- Support PostgreSQL/MySQL via read-only credentials.
- Evaluate on Spider/BIRD benchmarks (execution accuracy).
- Few-shot retrieval of similar past queries, semantic layer for business metrics.
- Voice input and Hindi speech support.
- Role-based access and query audit logs.

## 12. Conclusion
The assistant shows how generative AI can make data accessible to non-technical users while keeping the database safe through layered controls, and it is ready to deploy as a single Streamlit app with no external services except the optional LLM API.

## 13. References
- Google Gemini API documentation: https://ai.google.dev
- Streamlit documentation: https://docs.streamlit.io
- Plotly Express: https://plotly.com/python/plotly-express/
- Yu et al., *Spider: A Large-Scale Human-Labeled Dataset for Text-to-SQL*, EMNLP 2018.
- Li et al., *BIRD: Can LLM Already Serve as a Database Interface?*, NeurIPS 2023.
