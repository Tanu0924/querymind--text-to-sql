"""Text-to-SQL Analytics Assistant: ask business questions in plain English / Hinglish, get SQL + charts.

Run:  streamlit run app.py
"""
import os

import pandas as pd
import streamlit as st

from modules import db
from modules.charts import build_figure, metric_display
from modules.nl2sql import DEFAULT_MODEL, EXAMPLES, MODEL_CHOICES, Text2SQLEngine
from modules.sql_guard import UnsafeSQLError

st.set_page_config(page_title="Text-to-SQL Analytics Assistant", page_icon="📊", layout="wide")

CSS = """
<style>
.hero { background: linear-gradient(135deg,#0f172a 0%,#1e3a8a 60%,#2563eb 100%);
        padding: 1.5rem 2rem; border-radius: 16px; color: #fff; margin-bottom: 1rem; }
.hero h1 { margin: 0; font-size: 1.8rem; font-weight: 700; }
.hero p { margin: .3rem 0 0; opacity: .85; }
.badge { display:inline-block; padding:.15rem .7rem; border-radius:999px; font-size:.75rem; font-weight:600; }
.badge-demo { background:#fef0c7; color:#b54708; }
.badge-live { background:#d1fadf; color:#027a48; }
.metric-box { border:1px solid #e5e7eb; border-radius:14px; padding:1rem 1.4rem; background:#fff;
              box-shadow:0 2px 8px rgba(16,24,40,.06); display:inline-block; min-width:240px; }
.metric-box .l { font-size:.75rem; text-transform:uppercase; letter-spacing:.06em; color:#667085; }
.metric-box .v { font-size:2rem; font-weight:700; color:#101828; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ state
def init_state():
    if "history" not in st.session_state:
        st.session_state.history = []
    if "conn" not in st.session_state:
        st.session_state.conn = db.build_demo_db()
        st.session_state.is_demo_db = True
        st.session_state.source_name = "Sample sales database"
    if "pending" not in st.session_state:
        st.session_state.pending = None


def sidebar() -> Text2SQLEngine:
    with st.sidebar:
        st.markdown("## 📊 Text-to-SQL Assistant")
        default_key = ""
        try:
            default_key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            pass
        default_key = default_key or os.environ.get("GEMINI_API_KEY", "")
        key = st.text_input("Google Gemini API key", type="password", value=default_key,
                            help="Free key: aistudio.google.com. Leave empty for demo mode.")
        model = st.selectbox("Model", MODEL_CHOICES, index=MODEL_CHOICES.index(DEFAULT_MODEL))
        engine = Text2SQLEngine(key, model)
        if engine.demo_mode:
            st.markdown('<span class="badge badge-demo">DEMO MODE</span>', unsafe_allow_html=True)
            st.caption("Template-based answers on the sample database. Add a key for free-form questions "
                       "and your own CSV.")
        else:
            st.markdown('<span class="badge badge-live">LIVE · GEMINI</span>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### Data source")
        up = st.file_uploader("Upload your own CSV (needs API key)", type=["csv"])
        c1, c2 = st.columns(2)
        if up is not None and c1.button("Use CSV", use_container_width=True):
            try:
                df = pd.read_csv(up)
                st.session_state.conn = db.build_db_from_csv(df)
                st.session_state.is_demo_db = False
                st.session_state.source_name = f"Uploaded: {up.name}"
                st.session_state.history = []
                st.rerun()
            except Exception as exc:
                st.error(f"Could not load CSV: {exc}")
        if c2.button("Sample DB", use_container_width=True):
            st.session_state.conn = db.build_demo_db()
            st.session_state.is_demo_db = True
            st.session_state.source_name = "Sample sales database"
            st.session_state.history = []
            st.rerun()
        st.caption(f"Active: **{st.session_state.source_name}**")

        with st.expander("Database schema"):
            for table, cols in db.get_tables(st.session_state.conn).items():
                st.markdown(f"**{table}**")
                st.code(", ".join(cols), language=None)

        st.markdown("### Try these")
        if st.session_state.is_demo_db:
            for ex in EXAMPLES:
                if st.button(ex, key=f"ex_{ex}", use_container_width=True):
                    st.session_state.pending = ex
        else:
            st.caption("Ask anything about your CSV, e.g. 'total by month' or 'top 5 rows by amount'.")

        st.markdown("---")
        if st.button("🗑️ Clear conversation", use_container_width=True):
            st.session_state.history = []
            st.rerun()
        with st.expander("How it works"):
            st.markdown(
                "1. Your question + the schema go to Gemini\n"
                "2. Gemini returns **SQL + chart spec** (JSON)\n"
                "3. A **SQL guard** allows only one read-only SELECT\n"
                "4. SQL runs on a **read-only** in-memory SQLite DB\n"
                "5. Result is charted with Plotly\n"
                "6. If SQL errors, the model gets the error and **self-repairs** once"
            )
    return engine


# ------------------------------------------------------------------ rendering
def render_entry(entry: dict, idx: int):
    with st.chat_message("user"):
        st.markdown(entry["question"])
    with st.chat_message("assistant"):
        if entry.get("error"):
            st.error(entry["error"])
            return
        if entry.get("fallback"):
            st.warning(entry["explanation"])
        st.markdown(entry["summary"])
        df, chart = entry["df"], entry["chart"]
        if chart.get("type") == "metric" and not df.empty:
            label, value = metric_display(df, chart)
            st.markdown(f'<div class="metric-box"><div class="l">{label}</div><div class="v">{value}</div></div>',
                        unsafe_allow_html=True)
        else:
            fig = build_figure(df, chart)
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True, key=f"fig_{idx}")
        if not entry.get("fallback") and entry.get("explanation"):
            st.caption(entry["explanation"])
        with st.expander("Generated SQL"):
            st.code(entry["sql"], language="sql")
        with st.expander(f"Result table ({len(df)} rows)"):
            st.dataframe(df, use_container_width=True)
            st.download_button("⬇️ Download CSV", df.to_csv(index=False), file_name=f"result_{idx + 1}.csv",
                               mime="text/csv", key=f"dl_{idx}")


def ask(engine: Text2SQLEngine, question: str):
    entry = {"question": question}
    try:
        with st.spinner("Writing SQL and running it..."):
            res = engine.answer(st.session_state.conn, question, st.session_state.history,
                                st.session_state.is_demo_db)
        entry.update(res)
    except UnsafeSQLError as exc:
        entry["error"] = f"Blocked for safety: {exc}"
    except Exception as exc:
        entry["error"] = (f"Could not answer that: {exc}. Try rephrasing, check your API key/quota, "
                          "or clear the key to use demo mode.")
    st.session_state.history.append(entry)


# ------------------------------------------------------------------ main
def main():
    init_state()
    engine = sidebar()
    st.markdown('<div class="hero"><h1>📊 Text-to-SQL Analytics Assistant</h1>'
                '<p>Ask business questions in English or Hinglish. Get the SQL, the answer and a chart.</p></div>',
                unsafe_allow_html=True)

    question = st.chat_input("e.g. Pichhle mahine ki sales kitni thi?  |  Top 5 products by revenue")
    if st.session_state.pending:
        question, st.session_state.pending = st.session_state.pending, None
    if question:
        ask(engine, question)

    if not st.session_state.history:
        st.info("👋 Ask a question below or click an example in the sidebar. The sample database has 3,000 orders "
                "across customers, products and regions for the last 12 months (in ₹).")
    for i, entry in enumerate(st.session_state.history):
        render_entry(entry, i)


if __name__ == "__main__":
    main()
