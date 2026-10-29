"""SQL safety validation. Only a single read-only SELECT statement is allowed."""
import re

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|"
    r"truncate|reindex|grant|revoke|exec|execute)\b",
    re.IGNORECASE,
)
MAX_ROWS = 1000


class UnsafeSQLError(ValueError):
    """Raised when generated SQL is not a safe read-only query."""


def clean_sql(sql: str) -> str:
    sql = (sql or "").strip()
    sql = re.sub(r"^```(?:sql)?|```$", "", sql, flags=re.MULTILINE | re.IGNORECASE).strip()
    return sql.rstrip(";").strip()


def validate_sql(sql: str) -> str:
    """Return a safe version of the SQL (row-limited) or raise UnsafeSQLError."""
    sql = clean_sql(sql)
    if not sql:
        raise UnsafeSQLError("No SQL was generated.")
    if "--" in sql or "/*" in sql:
        raise UnsafeSQLError("SQL comments are not allowed.")
    if ";" in sql:
        raise UnsafeSQLError("Only a single SQL statement is allowed.")
    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    bad = FORBIDDEN.search(sql)
    if bad:
        raise UnsafeSQLError(f"Forbidden keyword in query: {bad.group(0).upper()}")
    return f"SELECT * FROM (\n{sql}\n) LIMIT {MAX_ROWS}"
