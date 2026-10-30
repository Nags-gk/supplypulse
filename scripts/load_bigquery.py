"""Optional and UNTESTED: load the curated Parquet into BigQuery.

Not run in CI and not yet run by the author. Needs a Google Cloud project (BigQuery sandbox works) and
`gcloud auth application-default login`:
    pip install -r requirements-bigquery.txt
    python scripts/load_bigquery.py --project YOUR_PROJECT --dataset supplypulse_raw
Porting the dbt models is a separate step: warehouse/models/staging/_sources.yml reads Parquet through DuckDB,
so it must be re-pointed at the loaded table, and any DuckDB-specific SQL checked, before `dbt build --target bigquery`.
"""
import argparse
from pathlib import Path

from google.cloud import bigquery


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="supplypulse_raw")
    ap.add_argument("--location", default="US")
    ap.add_argument("--curated", default="data/curated/orders")
    a = ap.parse_args()

    client = bigquery.Client(project=a.project)
    ds = bigquery.Dataset(f"{a.project}.{a.dataset}")
    ds.location = a.location
    client.create_dataset(ds, exists_ok=True)

    files = sorted(Path(a.curated).rglob("*.parquet"))
    if not files:
        raise SystemExit(f"no parquet files under {a.curated}; run the Spark ETL first")
    cfg = bigquery.LoadJobConfig(source_format=bigquery.SourceFormat.PARQUET, write_disposition="WRITE_TRUNCATE")
    table = f"{a.project}.{a.dataset}.orders"
    first = True
    for f in files:
        cfg.write_disposition = "WRITE_TRUNCATE" if first else "WRITE_APPEND"
        with open(f, "rb") as fh:
            client.load_table_from_file(fh, table, job_config=cfg).result()
        first = False
    print(f"loaded {client.get_table(table).num_rows} rows into {table}")


if __name__ == "__main__":
    main()
