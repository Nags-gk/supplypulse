import pytest

from supplypulse.agent.eval_set import CASES
from supplypulse.agent.guardrails import UnsafeSQL, validate_sql
from supplypulse.agent.text_to_sql import ask, clean_sql

SQL_OK = "select shipping_mode, count(*) from fct_order_items group by 1"


@pytest.mark.parametrize("sql", [
    "drop table fct_order_items", "delete from fct_order_items", "select * from fct_order_items; select 1",
    "select * from secret_table", "select * from read_csv('/etc/passwd')", "select customer_email from dim_customer",
    "copy fct_order_items to '/tmp/x.csv'", "attach 'x.db'", "select * from main.fct_order_items",
])
def test_unsafe_sql_is_blocked(sql):
    with pytest.raises(UnsafeSQL):
        validate_sql(sql)


def test_limit_is_added_and_capped():
    assert "LIMIT 200" in validate_sql(SQL_OK)
    assert "LIMIT 200" in validate_sql(SQL_OK + " limit 5000")
    assert "LIMIT 5" in validate_sql(SQL_OK + " limit 5")


def test_cte_names_are_allowed():
    assert validate_sql("with t as (select * from kpi_daily) select count(*) from t")


def test_clean_sql_strips_fences():
    assert clean_sql("```sql\nselect 1;\n```") == "select 1"


def test_every_gold_query_passes_guardrails():
    for q, gold in CASES:
        if gold:
            validate_sql(gold)


def test_ask_repairs_one_sql_error_then_succeeds(tmp_path):
    import duckdb
    db = str(tmp_path / "t.duckdb")
    con = duckdb.connect(db)
    con.execute("create table fct_order_items as select 'A' as shipping_mode")
    con.close()
    replies = iter(["select nope from fct_order_items", "select shipping_mode from fct_order_items"])
    a = ask("q", db, llm=lambda p: next(replies), context="ctx")
    assert a.attempts == 2 and a.rows == [("A",)] and a.error is None


def test_ask_reports_blocked_sql(tmp_path):
    import duckdb
    db = str(tmp_path / "t.duckdb")
    duckdb.connect(db).close()
    a = ask("q", db, llm=lambda p: "drop table x", context="ctx")
    assert a.error and a.error.startswith("blocked")
