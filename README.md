# Course Progress Data Analyst Agent

A simple Streamlit dashboard with one AI agent (Google Gemini) that analyzes student course progress and completion rates in a PostgreSQL database.

## What the agent does

You type a question in plain language (any language). The agent:

1. Writes a PostgreSQL `SELECT` query based on the database schema in its instructions.
2. Runs it through the `run_sql` tool, which can only read data.
3. Reads the result, runs more queries if needed (up to 6), and answers in the language of your question.

The dashboard shows each SQL query the agent ran, so you can check the answer.

**Example questions:**
- Which course level has the highest completion rate?
- What is the average progress of users on the Premium plan?
- Яка частка зарахувань доходить до стадії "explored"?

## Data used

| Table | Used for |
|---|---|
| `enrollments` | Main table: one row per user × course with `progress_pct`, `funnel_state`, `is_certified` |
| `dim_course` | Course name, level, domain, specialization, partner |
| `users` | Country, plan, persona, age band, device |
| `weekly_activity` | Weekly minutes watched, quiz attempts and scores |

**Definitions:**
- **Completed** means `is_certified = 1`.
- **Average progress** is `AVG(LEAST(progress_pct, 100))`, because a few rows go above 100.
- The completion charts include only courses and domains with at least 100 enrollments, because small courses produce noisy rates.

## Safety

Every query is read-only, enforced by four layers:
- the database user is read-only;
- each query runs in a `READ ONLY` transaction with a 15-second timeout;
- agent SQL must be a single `SELECT`/`WITH` statement, and data-changing keywords are rejected;
- agent results are capped at 200 rows.

Secrets live only in `.env`, which git ignores.

## How to run (Windows)

```powershell
# 1. Create and activate the virtual environment (skip creation if .venv already exists)
python -m venv .venv
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure secrets
copy .env.example .env
#    then edit .env: set DATABASE_URL and GEMINI_API_KEY (GEMINI_MODEL is optional)

# 4. Start the dashboard
streamlit run app.py
```

The app opens at http://localhost:8501.

## Files

- `app.py`: Streamlit dashboard (KPIs, charts, question box)
- `agent.py`: Gemini agent (system prompt and `run_sql` tool)
- `db.py`: database connection, dashboard queries, safe query runner
