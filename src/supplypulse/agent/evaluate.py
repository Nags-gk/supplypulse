"""Execution-accuracy evaluation: a case passes when the generated query returns the same result set as the gold query.

    python -m supplypulse.agent.evaluate --dry     # offline: checks every gold query passes the guardrails and runs
    GEMINI_API_KEY=... python -m supplypulse.agent.evaluate   # live: scores Gemini, writes site/data/agent_eval.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import duckdb

from .eval_set import CASES
from .guardrails import validate_sql
from .text_to_sql import MODEL, ROOT, ask, schema_context


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


def score(db: str, llm, out: str | None = None, pause: float = 7.0) -> dict:
    ctx = schema_context()
    con = duckdb.connect(db, read_only=True)
    results = []
    for q, gold in CASES:
        a, api_err = None, None
        for wait in (0, 15, 45):  # retry transient API errors (503 high demand, 429 rate limit)
            time.sleep(wait)
            try:
                a = ask(q, db, llm, ctx)
                break
            except Exception as e:  # noqa: BLE001
                api_err = f"api: {e}"[:300]
        if a is None:  # API never answered: excluded from accuracy, reported separately
            print(f"[{len(results) + 1}/{len(CASES)}] API FAILURE {q}: {api_err[:120]}", flush=True)
            results.append({"question": q, "pass": False, "answerable": gold is not None, "sql": "", "error": api_err, "attempts": 0, "api_failure": True})
            continue
        time.sleep(pause)  # stay under free-tier requests-per-minute limits
        if gold is None:
            ok = (not a.error) and a.rows[:1] == [("UNANSWERABLE",)]
        else:
            ok = (not a.error) and same_result(a.rows, con.execute(validate_sql(gold, 10_000)).fetchall())
        print(f"[{len(results) + 1}/{len(CASES)}] {'PASS' if ok else 'MISS'} {q}", flush=True)
        results.append({"question": q, "pass": bool(ok), "answerable": gold is not None, "sql": a.sql, "error": a.error, "attempts": a.attempts})
    scored = [r for r in results if not r.get("api_failure")]
    ans = [r for r in scored if r["answerable"]]
    ref = [r for r in scored if not r["answerable"]]
    rep = {"cases": len(results), "scored_cases": len(scored), "api_failures": len(results) - len(scored),
           "execution_accuracy": sum(r["pass"] for r in ans) / len(ans) if ans else None, "answerable_scored": len(ans),
           "refusal_accuracy": sum(r["pass"] for r in ref) / len(ref) if ref else None, "refusals_scored": len(ref), "results": results}
    rep["model"] = os.environ.get("SP_GEMINI_MODEL", MODEL)
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
    fmt = lambda v: "n/a" if v is None else f"{v:.0%}"  # noqa: E731
    print(f"execution accuracy {fmt(r['execution_accuracy'])} on {r['answerable_scored']} answered questions; "
          f"refusal accuracy {fmt(r['refusal_accuracy'])} on {r['refusals_scored']}; API failures {r['api_failures']} of {r['cases']}")
    for x in r["results"]:
        if not x["pass"]:
            print("MISS:", x["question"], "|", x["error"] or x["sql"])
