# SupplyPulse

Supply chain analytics on 180,519 order lines: a PySpark ETL with a data-quality gate, a dbt star schema, governed metrics and a data catalog, hierarchical demand forecasting, KPI anomaly detection, a guarded Gemini text-to-SQL agent, and a static dashboard published on GitHub Pages.

**Live dashboard:** https://nags-gk.github.io/supplypulse/ (published by the `ci-and-pages` workflow on every push to `main`)

## What it does

| Stage | Code | Result |
|---|---|---|
| Ingest | `scripts/fetch_data.py` | Pinned download, size and row-count check |
| ETL | `src/supplypulse/etl/spark_etl.py` | 42 columns kept, 11 PII/empty columns dropped, 11 quality rules + duplicate check, failing rows go to a quarantine table, Parquet partitioned by year and month, `good + bad == raw` asserted |
| Warehouse | `warehouse/` (dbt-duckdb) | Star schema (5 dimensions, 1 fact), 6 KPI marts, 51 of 51 dbt checks pass (38 data tests) |
| Metrics | `metrics/metrics.yml`, `catalog/metrics_check.py` | 11 metrics defined once as SQL, executed and reconciled to the marts |
| Catalog | `catalog/build_catalog.py`, `docs/DATA_CATALOG.md` | Tables, lineage, test counts, dashboard inventory, source caveats |
| Forecast | `src/supplypulse/forecast/` | Weekly demand at total, market and market-by-department level; statsforecast + LightGBM; rolling-origin backtest scored by WAPE; split-conformal intervals |
| Anomalies | `src/supplypulse/anomaly/detect.py` | Robust rolling z-score (median/MAD) on 6 weekly KPIs, validated by injecting known spikes |
| Agent | `src/supplypulse/agent/` | Gemini text-to-SQL with a sqlglot guardrail (single SELECT, table allowlist, blocked columns, row cap) and a 17-question evaluation set (15 answerable, 2 that must be refused) |
| Dashboard | `site/` | D3 charts, table views, keyboard-accessible tooltips, light/dark |
| CI | `.github/workflows/ci.yml` | Tests, full pipeline, Pages deploy |

## Findings (all produced by this repo's code)

- Weekly order lines fell 60% in the week of 2 Oct 2017 (about 1,199 a week to about 482). The product catalogue shrank from 100 to 30 products and units per line fell from 2.18 to 1.01. Service levels did not change.
- Shipping mode, not market, explains late deliveries. First Class is promised in 1 day and was late on 100% of lines; the on-time rate by market spans 42.3% to 43.2%.
- Forecasting through the Oct 2017 break with a model trained on the old regime overshoots by about 148%. Pre-break, the weekly total is nearly flat (AutoETS WAPE 2.5%, naive 2.9%), so the total is easy but not impressive. At market and department level, LightGBM with top-down reconciliation beats naive (WAPE 37% vs 43%, and 42% vs 46%), and raw bottom-up LightGBM does not.
- Anomaly detector (3.5 robust sigma, 143 clean pre-break weeks): catches 92% to 99% of injected 6-sigma spikes but only 24% to 31% of 3-sigma spikes, with 0% to 2.1% false alarms per normal week depending on the KPI. Of the 25 alerts on real data, 13 are order-line alerts from the Oct 2017 volume break.

## Limits you should know before trusting any number

- **The data looks semi-synthetic.** Weekly totals are almost constant and delivery outcomes are deterministic by shipping mode. Treat the findings as a demonstration of method, not as claims about a real business.
- **No inventory, supplier or shipped-quantity fields.** On-time-in-full and inventory turns are not computed.
- **The quarantine gate caught nothing on the real data** (0 of 180,519 rows). Its behaviour is shown by unit tests with injected defects (`tests/test_quality_gate.py`).
- **After the break there are only 17 weeks**, too few to learn from; the forecast for the next 8 weeks is a flat non-seasonal ETS and its band is narrow.
- **The 80% conformal interval** covered 87.5% of an 8-week holdout; that is a small sample.
- **Text-to-SQL accuracy is not reported yet.** The evaluation harness runs offline against gold queries (`python -m supplypulse.agent.evaluate --dry`). A live score needs a `GEMINI_API_KEY` secret; until that has been run, no accuracy figure is claimed.
- **BigQuery** is a load script only (`scripts/load_bigquery.py`). It has not been run, and the dbt models are not ported to it.

## Run it

Needs Python 3.12+, Java 17 (for Spark) and about 1 GB of disk.

```bash
pip install -r requirements.txt
python scripts/fetch_data.py
export PYTHONPATH=src
python -m supplypulse.etl.spark_etl
(cd warehouse && DBT_PROFILES_DIR=. dbt build)
python -m supplypulse.catalog.metrics_check
python -m supplypulse.forecast.run_forecast
python -m supplypulse.anomaly.detect
python -m supplypulse.catalog.export_site_data
python -m supplypulse.catalog.build_catalog
python -m pytest -q tests
python -m http.server --directory site 8000   # open http://localhost:8000
```

Ask the agent a question (needs `GEMINI_API_KEY` from Google AI Studio):

```bash
GEMINI_API_KEY=... python -m supplypulse.agent.text_to_sql "Which shipping mode has the highest late delivery rate?"
```

## Data

DataCo Smart Supply Chain for Big Data Analysis. Constante, F., Silva, F., Pereira, A. (2019), Mendeley Data, licensed CC BY 4.0. Read from a pinned GitHub mirror; the raw file is not stored in this repository. Customer personal fields are dropped in the ETL.
