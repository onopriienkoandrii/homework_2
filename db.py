"""Database access: dashboard KPI queries and a safe read-only query runner for the agent."""

import os
import re
from decimal import Decimal

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")

# SQLAlchemy needs the "postgresql+psycopg2://" scheme; accept a plain "postgresql://" URL too.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

AGENT_MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 15000

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|merge|call|vacuum|lock|comment)\b",
    re.IGNORECASE,
)


def _read(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a query inside a READ ONLY transaction with a timeout, then roll back."""
    with engine.connect() as conn:
        with conn.begin() as tx:
            # Set per-transaction (not as a connection option) so it also works through Neon's pooler.
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            df = pd.read_sql(text(sql), conn, params=params)
            tx.rollback()
    # Postgres NUMERIC arrives as Decimal objects; convert to float for pandas/plotly/JSON.
    for col in df.columns:
        if df[col].dtype == object and df[col].map(lambda v: isinstance(v, Decimal)).any():
            df[col] = df[col].astype(float)
    return df


def run_select(sql: str, max_rows: int = AGENT_MAX_ROWS) -> pd.DataFrame:
    """Validate and run a single SELECT/WITH query written by the agent."""
    query = sql.strip().rstrip(";").strip()
    if ";" in query:
        raise ValueError("Only a single SQL statement is allowed.")
    if not re.match(r"^(select|with)\b", query, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(query):
        raise ValueError("Query contains a forbidden keyword; only read-only SELECT queries are allowed.")
    # Wrap the query so the row limit applies whatever the agent wrote.
    return _read(f"SELECT * FROM ({query}) AS q LIMIT {int(max_rows)}")


def get_kpis() -> dict:
    df = _read(
        """
        SELECT COUNT(*)                          AS total_enrollments,
               AVG(LEAST(progress_pct, 100))     AS avg_progress,
               SUM(is_certified)                 AS completed,
               AVG(is_certified::numeric) * 100  AS completion_rate
        FROM enrollments
        """
    )
    return df.iloc[0].to_dict()


def completion_by_course(min_enrollments: int = 100, top_n: int = 15) -> pd.DataFrame:
    return _read(
        """
        SELECT d.course,
               COUNT(*)                              AS enrollments,
               SUM(e.is_certified)                   AS completed,
               AVG(e.is_certified::numeric) * 100    AS completion_rate
        FROM enrollments e
        JOIN dim_course d ON d.course_id = e.course_id
        GROUP BY d.course_id, d.course
        HAVING COUNT(*) >= :min_enrollments
        ORDER BY completion_rate DESC
        LIMIT :top_n
        """,
        {"min_enrollments": min_enrollments, "top_n": top_n},
    )


def completion_by_domain(min_enrollments: int = 100, top_n: int = 15) -> pd.DataFrame:
    return _read(
        """
        SELECT d.domain,
               COUNT(*)                              AS enrollments,
               SUM(e.is_certified)                   AS completed,
               AVG(e.is_certified::numeric) * 100    AS completion_rate
        FROM enrollments e
        JOIN dim_course d ON d.course_id = e.course_id
        GROUP BY d.domain
        HAVING COUNT(*) >= :min_enrollments
        ORDER BY completion_rate DESC
        LIMIT :top_n
        """,
        {"min_enrollments": min_enrollments, "top_n": top_n},
    )


def funnel() -> pd.DataFrame:
    return _read(
        """
        SELECT funnel_state, COUNT(*) AS enrollments
        FROM enrollments
        GROUP BY funnel_state
        ORDER BY CASE funnel_state
                   WHEN 'registered' THEN 1 WHEN 'viewed' THEN 2
                   WHEN 'explored' THEN 3 WHEN 'certified' THEN 4 ELSE 5 END
        """
    )
