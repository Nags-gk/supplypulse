"""PySpark ETL: raw DataCo order lines -> curated Parquet + quarantine.

Steps
  1. Read the raw CSV (ISO-8859-1) with an explicit header.
  2. Drop PII and empty columns (customer name/email/password/street/zip, product image, ...).
  3. Rename to snake_case and cast types; parse order and ship timestamps.
  4. Apply data-quality rules. Rows that fail any rule go to a quarantine table with the failed
     rule names; duplicate order_item_id rows keep the earliest record.
  5. Write partitioned Parquet (order_year / order_month) and an ETL report as JSON.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

# raw header -> clean column name (only columns that are kept)
COLUMN_MAP: dict[str, str] = {
    "Type": "payment_type",
    "Days for shipping (real)": "days_shipping_real",
    "Days for shipment (scheduled)": "days_shipping_scheduled",
    "Benefit per order": "benefit_per_order",
    "Sales per customer": "sales_per_customer",
    "Delivery Status": "delivery_status",
    "Late_delivery_risk": "late_delivery_risk",
    "Category Id": "category_id",
    "Category Name": "category_name",
    "Customer City": "customer_city",
    "Customer Country": "customer_country",
    "Customer Id": "customer_id",
    "Customer Segment": "customer_segment",
    "Customer State": "customer_state",
    "Department Id": "department_id",
    "Department Name": "department_name",
    "Latitude": "store_latitude",
    "Longitude": "store_longitude",
    "Market": "market",
    "Order City": "order_city",
    "Order Country": "order_country",
    "order date (DateOrders)": "order_ts_raw",
    "Order Id": "order_id",
    "Order Item Discount": "item_discount",
    "Order Item Discount Rate": "item_discount_rate",
    "Order Item Id": "order_item_id",
    "Order Item Product Price": "item_product_price",
    "Order Item Profit Ratio": "item_profit_ratio",
    "Order Item Quantity": "item_quantity",
    "Sales": "sales",
    "Order Item Total": "item_total",
    "Order Profit Per Order": "order_profit",
    "Order Region": "order_region",
    "Order State": "order_state",
    "Order Status": "order_status",
    "Product Card Id": "product_id",
    "Product Category Id": "product_category_id",
    "Product Name": "product_name",
    "Product Price": "product_price",
    "Product Status": "product_status",
    "shipping date (DateOrders)": "ship_ts_raw",
    "Shipping Mode": "shipping_mode",
}

# columns that are never carried forward (PII, masked secrets, empty or link-only fields)
DROPPED_COLUMNS = [
    "Customer Email",
    "Customer Fname",
    "Customer Lname",
    "Customer Password",
    "Customer Street",
    "Customer Zipcode",
    "Order Zipcode",
    "Order Customer Id",
    "Order Item Cardprod Id",
    "Product Description",
    "Product Image",
]

DELIVERY_STATUSES = ["Advance shipping", "Late delivery", "Shipping canceled", "Shipping on time"]
ORDER_STATUSES = [
    "COMPLETE", "PENDING", "CLOSED", "PENDING_PAYMENT", "CANCELED",
    "PROCESSING", "SUSPECTED_FRAUD", "ON_HOLD", "PAYMENT_REVIEW",
]
TS_FORMAT = "M/d/yyyy H:mm"


def build_spark(app: str = "supplypulse-etl", cores: str = "*") -> SparkSession:
    return (
        SparkSession.builder.appName(app)
        .master(f"local[{cores}]")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.legacy.timeParserPolicy", "CORRECTED")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )


def read_raw(spark: SparkSession, path: str) -> DataFrame:
    df = (
        spark.read.option("header", True)
        .option("encoding", "ISO-8859-1")
        .option("quote", '"')
        .option("escape", '"')
        .option("multiLine", False)
        .csv(path)
    )
    # headers in the source occasionally carry padding; normalise before mapping
    return df.toDF(*[c.strip() for c in df.columns])


def project_and_cast(df: DataFrame) -> DataFrame:
    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise ValueError(f"raw file is missing expected columns: {missing}")
    df = df.select([F.col(f"`{raw}`").alias(clean) for raw, clean in COLUMN_MAP.items()])

    int_cols = [
        "days_shipping_real", "days_shipping_scheduled", "late_delivery_risk", "category_id",
        "customer_id", "department_id", "order_id", "order_item_id", "item_quantity",
        "product_id", "product_category_id", "product_status",
    ]
    dbl_cols = [
        "benefit_per_order", "sales_per_customer", "store_latitude", "store_longitude",
        "item_discount", "item_discount_rate", "item_product_price", "item_profit_ratio",
        "sales", "item_total", "order_profit", "product_price",
    ]
    for c in int_cols:
        df = df.withColumn(c, F.col(c).cast("int"))
    for c in dbl_cols:
        df = df.withColumn(c, F.col(c).cast("double"))
    for c in ("product_name", "category_name", "shipping_mode", "market", "order_region"):
        df = df.withColumn(c, F.trim(F.col(c)))

    return (
        df.withColumn("order_ts", F.to_timestamp("order_ts_raw", TS_FORMAT))
        .withColumn("ship_ts", F.to_timestamp("ship_ts_raw", TS_FORMAT))
        .drop("order_ts_raw", "ship_ts_raw")
        .withColumn("order_date", F.to_date("order_ts"))
        .withColumn("order_year", F.year("order_ts"))
        .withColumn("order_month", F.month("order_ts"))
    )


def quality_rules() -> dict[str, Column]:
    """rule name -> condition that must be TRUE for a valid row (NULL counts as a failure)."""
    return {
        "order_id_present": F.col("order_id").isNotNull(),
        "order_item_id_present": F.col("order_item_id").isNotNull(),
        "order_ts_parsed": F.col("order_ts").isNotNull(),
        "ship_ts_parsed": F.col("ship_ts").isNotNull(),
        "ship_not_before_order": F.col("ship_ts") >= F.col("order_ts"),
        "quantity_positive": F.col("item_quantity") > 0,
        "sales_non_negative": F.col("sales") >= 0,
        "shipping_days_non_negative": F.col("days_shipping_real") >= 0,
        "delivery_status_valid": F.col("delivery_status").isin(DELIVERY_STATUSES),
        "order_status_valid": F.col("order_status").isin(ORDER_STATUSES),
        "late_flag_binary": F.col("late_delivery_risk").isin(0, 1),
    }


def apply_quality_gate(df: DataFrame) -> tuple[DataFrame, DataFrame, dict[str, int]]:
    rules = quality_rules()
    # NOTE: array_remove(arr, NULL) returns NULL in Spark, so drop the null placeholders with filter().
    failed = F.filter(
        F.array(*[F.when(~F.coalesce(cond, F.lit(False)), F.lit(name)) for name, cond in rules.items()]),
        lambda x: x.isNotNull(),
    )
    flagged = df.withColumn("failed_rules", failed)

    # duplicates: keep the earliest row per order_item_id, quarantine the rest
    w = Window.partitionBy("order_item_id").orderBy(F.col("order_ts").asc_nulls_last(), F.col("order_id"))
    flagged = flagged.withColumn("_rn", F.row_number().over(w)).withColumn(
        "failed_rules",
        F.when(
            (F.col("_rn") > 1) & F.col("order_item_id").isNotNull(),
            F.array_union(F.col("failed_rules"), F.array(F.lit("duplicate_order_item_id"))),
        ).otherwise(F.col("failed_rules")),
    ).drop("_rn")

    flagged = flagged.cache()
    good = flagged.where(F.size("failed_rules") == 0).drop("failed_rules")
    bad = flagged.where(F.size("failed_rules") > 0)

    counts = {
        r["rule"]: r["n"]
        for r in flagged.select(F.explode("failed_rules").alias("rule")).groupBy("rule").agg(F.count("*").alias("n")).collect()
    }
    return good, bad, counts


def run(raw_path: str, curated_dir: str, quarantine_dir: str, report_path: str) -> dict:
    t0 = time.time()
    spark = build_spark()
    raw = read_raw(spark, raw_path)
    n_raw = raw.count()
    typed = project_and_cast(raw)
    good, bad, rule_counts = apply_quality_gate(typed)

    n_good = good.count()
    n_bad = bad.count()
    if n_good + n_bad != n_raw:
        raise RuntimeError(f"row reconciliation failed: {n_good} + {n_bad} != {n_raw}")

    (
        good.repartition("order_year", "order_month")
        .write.mode("overwrite")
        .partitionBy("order_year", "order_month")
        .parquet(curated_dir)
    )
    (
        bad.withColumn("failed_rules", F.concat_ws(",", "failed_rules"))
        .coalesce(1)
        .write.mode("overwrite")
        .parquet(quarantine_dir)
    )

    report = {
        "raw_rows": n_raw,
        "curated_rows": n_good,
        "quarantined_rows": n_bad,
        "quarantine_rate": round(n_bad / n_raw, 6) if n_raw else None,
        "failed_rule_counts": dict(sorted(rule_counts.items())),
        "dropped_pii_columns": DROPPED_COLUMNS,
        "kept_columns": len(COLUMN_MAP),
        "elapsed_seconds": round(time.time() - t0, 1),
        "spark_version": spark.version,
    }
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, indent=2))
    spark.stop()
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", default="data/raw/DataCoSupplyChainDataset.csv")
    p.add_argument("--curated", default="data/curated/orders")
    p.add_argument("--quarantine", default="data/quarantine/orders")
    p.add_argument("--report", default="data/exports/etl_report.json")
    a = p.parse_args()
    print(json.dumps(run(a.raw, a.curated, a.quarantine, a.report), indent=2))


if __name__ == "__main__":
    main()
