"""The Spark quality gate must quarantine each defect type and reconcile row counts exactly."""
from datetime import datetime as dt

import pytest

pyspark = pytest.importorskip("pyspark")
from pyspark.sql import types as T  # noqa: E402

from supplypulse.etl.spark_etl import apply_quality_gate, build_spark  # noqa: E402

SCHEMA = T.StructType([
    T.StructField("order_id", T.IntegerType()), T.StructField("order_item_id", T.IntegerType()),
    T.StructField("order_ts", T.TimestampType()), T.StructField("ship_ts", T.TimestampType()),
    T.StructField("item_quantity", T.IntegerType()), T.StructField("sales", T.DoubleType()),
    T.StructField("days_shipping_real", T.IntegerType()), T.StructField("delivery_status", T.StringType()),
    T.StructField("order_status", T.StringType()), T.StructField("late_delivery_risk", T.IntegerType()),
])


def row(item=1, **kw):
    base = dict(order_id=1, order_item_id=item, order_ts=dt(2016, 1, 1), ship_ts=dt(2016, 1, 3), item_quantity=1,
                sales=10.0, days_shipping_real=2, delivery_status="Shipping on time", order_status="COMPLETE",
                late_delivery_risk=0)
    base.update(kw)
    return tuple(base[f.name] for f in SCHEMA.fields)


@pytest.fixture(scope="module")
def spark():
    s = build_spark("tests", cores="2")
    yield s
    s.stop()


DEFECTS = {
    "order_id_present": dict(order_id=None),
    "order_ts_parsed": dict(order_ts=None),
    "ship_not_before_order": dict(ship_ts=dt(2015, 12, 31)),
    "quantity_positive": dict(item_quantity=0),
    "sales_non_negative": dict(sales=-1.0),
    "shipping_days_non_negative": dict(days_shipping_real=-2),
    "delivery_status_valid": dict(delivery_status="Teleported"),
    "order_status_valid": dict(order_status="LOST"),
    "late_flag_binary": dict(late_delivery_risk=2),
}


def test_each_defect_is_quarantined_under_its_own_rule(spark):
    rows = [row(item=1)] + [row(item=100 + i, **kw) for i, kw in enumerate(DEFECTS.values())]
    good, bad, counts = apply_quality_gate(spark.createDataFrame(rows, SCHEMA))
    assert good.count() == 1
    assert bad.count() == len(DEFECTS)
    for rule in DEFECTS:
        assert counts.get(rule, 0) >= 1, f"{rule} did not fire"


def test_duplicate_item_ids_keep_first_row_only(spark):
    rows = [row(item=5), row(item=5, order_ts=dt(2016, 2, 1), ship_ts=dt(2016, 2, 3)), row(item=6)]
    good, bad, counts = apply_quality_gate(spark.createDataFrame(rows, SCHEMA))
    assert good.count() == 2 and bad.count() == 1
    assert counts == {"duplicate_order_item_id": 1}


def test_good_plus_bad_equals_input(spark):
    rows = [row(item=i) for i in range(20)] + [row(item=50 + i, sales=-5.0) for i in range(7)]
    good, bad, _ = apply_quality_gate(spark.createDataFrame(rows, SCHEMA))
    assert good.count() + bad.count() == len(rows)
