"""SQL guardrails for LLM-generated queries: single read-only SELECT over an allowlist of tables, row-capped."""
from __future__ import annotations

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {
    "fct_order_items", "dim_date", "dim_product", "dim_customer", "dim_geography", "dim_shipping_mode",
    "kpi_daily", "kpi_monthly", "scorecard_shipping_mode", "scorecard_region", "scorecard_category", "demand_weekly",
}
BLOCKED_COLUMNS = {"customer_email", "customer_password", "customer_fname", "customer_lname", "customer_street"}
MAX_ROWS = 200


class UnsafeSQL(ValueError):
    pass


def validate_sql(sql: str, max_rows: int = MAX_ROWS) -> str:
    """Return a safe, LIMIT-capped version of `sql` or raise UnsafeSQL."""
    try:
        stmts = sqlglot.parse(sql, read="duckdb")
    except sqlglot.errors.ParseError as e:
        raise UnsafeSQL(f"cannot parse SQL: {e}") from e
    stmts = [s for s in stmts if s is not None]
    if len(stmts) != 1:
        raise UnsafeSQL("exactly one statement is allowed")
    tree = stmts[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.With)) and not isinstance(tree, exp.Query):
        raise UnsafeSQL("only SELECT statements are allowed")
    banned = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Copy, exp.Pragma, exp.Attach)
    if any(tree.find(b) for b in banned):
        raise UnsafeSQL("statement contains a write or command operation")
    cte_names = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if isinstance(t.this, exp.Anonymous) or t.args.get("db") or t.args.get("catalog"):
            raise UnsafeSQL("schema-qualified or function tables are not allowed")
        if t.name not in ALLOWED_TABLES and t.name not in cte_names:
            raise UnsafeSQL(f"table not allowed: {t.name}")
    for f in tree.find_all(exp.Anonymous):
        if f.name.lower().startswith(("read_", "glob", "duckdb_", "pragma", "install", "load")):
            raise UnsafeSQL(f"function not allowed: {f.name}")
    for c in tree.find_all(exp.Column):
        if c.name.lower() in BLOCKED_COLUMNS:
            raise UnsafeSQL(f"column not allowed: {c.name}")
    limit = tree.args.get("limit")
    if limit is None or int(limit.expression.name) > max_rows:
        tree = tree.limit(max_rows)
    return tree.sql(dialect="duckdb")
