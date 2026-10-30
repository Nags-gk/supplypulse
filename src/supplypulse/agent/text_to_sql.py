"""Natural-language questions to governed SQL, using Gemini with schema + metric definitions as context.

Flow: build prompt from the data catalog and metrics.yml -> Gemini returns SQL -> guardrails validate ->
run read-only on DuckDB -> on a SQL error, one repair attempt with the error message -> return rows.
Needs GEMINI_API_KEY (free tier from Google AI Studio). The client is injectable so tests run offline.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import duckdb
import yaml

from .guardrails import ALLOWED_TABLES, UnsafeSQL, validate_sql

MODEL = os.environ.get("SP_GEMINI_MODEL", "gemini-3.8-flash")
ROOT = Path(__file__).resolve().parents[3]


def schema_context(catalog_path: Path = ROOT / "site/data/catalog.json", metrics_path: Path = ROOT / "metrics/metrics.yml") -> str:
    cat = json.loads(Path(catalog_path).read_text())
    lines = ["DuckDB tables (use only these):"]
    for t in cat["tables"]:
        if t["name"] not in ALLOWED_TABLES:
            continue
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t["columns"])
        lines.append(f"- {t['name']} ({t['layer']}): {t['description']} Columns: {cols}")
    spec = yaml.safe_load(Path(metrics_path).read_text())
    lines.append("\nGoverned metric definitions (use these expressions on fct_order_items when a question names a metric):")
    for m in spec["metrics"]:
        lines.append(f"- {m['name']}: {m['expr']}")
    lines.append("\nDate columns: join dim_date d ON d.date_key = fct_order_items.order_date for year, month or week_start.")
    return "\n".join(lines)


SYSTEM = (
    "You translate business questions about supply chain orders into one DuckDB SELECT statement. "
    "Use only the listed tables and columns. Prefer the governed metric expressions. Return only SQL, no prose, no code fences. "
    "If the question cannot be answered from these tables (for example inventory, suppliers, or on-time-in-full), "
    "return exactly: SELECT 'UNANSWERABLE' AS reason"
)


def _gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    r = client.models.generate_content(model=MODEL, contents=prompt, config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0))
    return r.text


def clean_sql(text: str) -> str:
    return re.sub(r"^```(?:sql)?\s*|\s*```$", "", text.strip(), flags=re.I).strip().rstrip(";")


@dataclass
class Answer:
    question: str
    sql: str
    columns: list[str]
    rows: list[tuple]
    attempts: int
    error: str | None = None


def ask(question: str, db: str = str(ROOT / "data/supplypulse.duckdb"), llm: Callable[[str], str] = _gemini, context: str | None = None) -> Answer:
    context = context or schema_context()
    prompt = f"{context}\n\nQuestion: {question}\nSQL:"
    sql, err = "", None
    con = duckdb.connect(db, read_only=True)
    try:
        for attempt in (1, 2):
            sql = clean_sql(llm(prompt if attempt == 1 else f"{prompt}\n\nPrevious SQL:\n{sql}\nError: {err}\nReturn corrected SQL only."))
            try:
                safe = validate_sql(sql)
                cur = con.execute(safe)
                return Answer(question, safe, [d[0] for d in cur.description], cur.fetchall(), attempt)
            except UnsafeSQL as e:
                return Answer(question, sql, [], [], attempt, f"blocked: {e}")
            except duckdb.Error as e:
                err = str(e).splitlines()[0]
        return Answer(question, sql, [], [], 2, f"sql error: {err}")
    finally:
        con.close()


if __name__ == "__main__":
    import sys

    a = ask(" ".join(sys.argv[1:]) or "Which shipping mode has the highest late delivery rate?")
    print(a.sql, "\n", a.columns, "\n", *a.rows[:10], sep="\n") if not a.error else print(a.error, "\n", a.sql)
