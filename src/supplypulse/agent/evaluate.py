"""Execution-accuracy evaluation: a case passes when the generated query returns the same result set as the gold query.

    python -m supplypulse.agent.evaluate --dry     # offline: checks every gold query passes the guardrails and runs
    GEMINI_API_KEY=... python -m supplypulse.agent.evaluate   # live: scores Gemini, writes site/data/agent_eval.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from .eval_set import CASES
from .guardrails import validate_sql
from .text_to_sql import ROOT, ask, schema_context


def _norm(rows):
    def cell(v):
        return round(v, 4) if isinstance(v, float) else v
    return sorted(tuple(cell(v) for v in r) for r in rows)


def same_result(a, b) -> bool:
    return _norm(a) == _norm(b)


def dry(db: str) -> int:
    con = duckdb.connect(db, read_only=True)
    bad = 0
    for q, gold in CASES:
        if gold is None:
            continue
        try:
            con.execute(validate_sql(gold)).fetchall()
        except Exception as e:  # noqa: BLE001
            bad += 1
            print("FAIL", q, e)
    print(f"{sum(g is not None for _, g in CASES) - bad} gold queries valid, {bad} failed")
    return bad


def score(db: str, llm, out: str | None = None) -> dict:
    ctx = schema_context()
    con = duckdb.connect(db, read_only=True)
    results = []
    for q, gold in CASES:
        a = ask(q, db, llm, ctx)
        if gold is None:
            ok = (not a.error) and a.rows[:1] == [("UNANSWERABLE",)]
        else:
            ok = (not a.error) and same_result(a.rows, con.execute(validate_sql(gold, 10_000)).fetchall())
        results.append({"question": q, "pass": bool(ok), "answerable": gold is not None, "sql": a.sql, "error": a.error, "attempts": a.attempts})
    ans = [r for r in results if r["answerable"]]
    rep = {"cases": len(results), "execution_accuracy": sum(r["pass"] for r in ans) / len(ans),
           "refusal_accuracy": sum(r["pass"] for r in results if not r["answerable"]) / max(1, len(results) - len(ans)), "results": results}
    if out:
        Path(out).write_text(json.dumps(rep, indent=2))
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data/supplypulse.duckdb"))
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    if a.dry:
        raise SystemExit(1 if dry(a.db) else 0)
    from .text_to_sql import _gemini
    r = score(a.db, _gemini, str(ROOT / "site/data/agent_eval.json"))
    print(f"execution accuracy {r['execution_accuracy']:.0%} on {r['cases']} cases; refusal accuracy {r['refusal_accuracy']:.0%}")
    for x in r["results"]:
        if not x["pass"]:
            print("MISS:", x["question"], "|", x["error"] or x["sql"])
