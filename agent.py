"""Data Analyst Agent: Gemini writes SQL, runs it through a read-only tool, and explains the result."""

import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from db import AGENT_MAX_ROWS, run_select

load_dotenv()

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TOOL_CALLS = 6

SYSTEM_PROMPT = f"""
You are a Data Analyst Agent for an online-learning platform (Coursera-style data).
You answer questions about student course progress and completion rates using a PostgreSQL database.
Use the run_sql tool to query the data; never invent numbers. You may call it several times.

DATABASE SCHEMA (PostgreSQL, schema public):
- enrollments (one row per user x course enrollment, ~95k rows)
    enrollment_id, user_id, course_id, course_url, specialization_id, course_no,
    enrolled_at (TEXT date, two formats: 'YYYY-MM-DD' and 'DD.MM.YYYY'),
    completed_at (TEXT, mostly NULL), last_week_reached (int), n_weeks (int),
    progress_pct (numeric 0..~104), funnel_state ('registered','viewed','explored','certified'),
    is_certified (0/1)
- dim_course (one row per course, ~3k rows)
    course_id, course (name), level ('Beginner','Intermediate','Advanced','Unknown'), domain,
    specialization_name, partner, n_weeks, total_minutes, review_score, n_reviews, mean_stars
- users (one row per user, 40k rows)
    user_id, signup_date (date), country, plan, persona, age_band, device_primary
- weekly_activity (one row per enrollment x active week)
    enrollment_id, week_number, active_date (date), minutes_watched, quiz_attempts, quiz_score

JOINS: enrollments.course_id = dim_course.course_id; enrollments.user_id = users.user_id;
weekly_activity.enrollment_id = enrollments.enrollment_id.

BUSINESS RULES:
- "Completed" enrollment means is_certified = 1. Completion rate = AVG(is_certified::numeric) * 100.
- Average progress: use AVG(LEAST(progress_pct, 100)) because a few rows exceed 100.
- funnel_state is the furthest stage reached: registered -> viewed -> explored -> certified.
- To parse enrolled_at use:
  CASE WHEN enrolled_at ~ '^\\d{{4}}-' THEN to_date(enrolled_at, 'YYYY-MM-DD')
       ELSE to_date(enrolled_at, 'DD.MM.YYYY') END
- Many courses have very few enrollments. When ranking courses by a rate, filter to courses with
  enough enrollments (e.g. HAVING COUNT(*) >= 100) and mention the threshold.

SQL RULES:
- Only one SELECT (or WITH ... SELECT) statement per call. Never modify data.
- Results are capped at {AGENT_MAX_ROWS} rows, so aggregate in SQL instead of fetching raw rows.
- If a query returns an error, fix it and try again.

ANSWER RULES:
- Always answer in the same language as the user's question.
- Be concise: give the key numbers first (rounded sensibly), then a short interpretation.
- If the data cannot answer the question, say so plainly.
"""


class DataAnalystAgent:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or api_key.startswith("your-"):
            raise RuntimeError("GEMINI_API_KEY is not set. Add your key to the .env file.")
        self.client = genai.Client(api_key=api_key)
        self.model = os.getenv("GEMINI_MODEL") or DEFAULT_MODEL

    def ask(self, question: str) -> dict:
        """Answer a question. Returns {"answer": str, "queries": [sql, ...]}."""
        queries = []

        def run_sql(query: str) -> dict:
            """Run one read-only SQL SELECT query against the course PostgreSQL database.

            Args:
                query: A single PostgreSQL SELECT (or WITH ... SELECT) statement.

            Returns:
                A dict with "row_count" and "rows" (list of records), or "error" if the query failed.
            """
            queries.append(query)
            try:
                df = run_select(query)
                rows = json.loads(df.to_json(orient="records", date_format="iso", default_handler=str))
                return {"row_count": len(rows), "rows": rows}
            except Exception as exc:  # Send the error back so the model can fix its SQL.
                return {"error": str(exc)}

        response = self.client.models.generate_content(
            model=self.model,
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[run_sql],
                temperature=0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=MAX_TOOL_CALLS
                ),
            ),
        )
        answer = response.text or "The agent could not produce an answer. Try rephrasing the question."
        return {"answer": answer, "queries": queries}
