"""CSV -> DuckDB feed rules -> FastAPI JSON -> one static HTML page.  Run: uvicorn app:app --port 8000

Rules: one feed type per customer (the period type holding the most value), gap months read from the other
type only where the feed has no data, and sell-in cut at each customer's sell-out as-of month.
"""
import csv
import functools
from pathlib import Path

import duckdb
from fastapi import FastAPI
from fastapi.responses import FileResponse

HERE = Path(__file__).parent
D = HERE / "data"
app = FastAPI(title="Analytics dashboard demo")


@functools.cache
def build():
    con = duckdb.connect()
    for n in ("sellout", "sellin", "target"):
        con.execute(f"CREATE VIEW {n} AS SELECT * FROM read_csv_auto('{(D / (n + '.csv')).as_posix()}')")
    con.execute("""CREATE TABLE monthly AS
        SELECT channel, customer, period_type, date_trunc('month', period_start::DATE)::DATE AS month, SUM(value) AS value
        FROM sellout GROUP BY ALL""")
    con.execute("""CREATE TABLE feed AS
        SELECT channel, customer, period_type AS feed_type FROM monthly
        GROUP BY channel, customer, period_type
        QUALIFY ROW_NUMBER() OVER (PARTITION BY channel, customer ORDER BY SUM(value) DESC) = 1""")
    # shortcut: assumes two period types; with three, a gap month could match two non-feed types
    con.execute("""CREATE TABLE sellout_month AS
        SELECT m.channel, m.customer, m.month, m.value
        FROM monthly m JOIN feed f USING (channel, customer)
        WHERE m.period_type = f.feed_type
           OR NOT EXISTS (SELECT 1 FROM monthly k WHERE k.channel = m.channel AND k.customer = m.customer
                          AND k.period_type = f.feed_type AND k.month = m.month)""")
    con.execute("""CREATE TABLE last_seen AS SELECT channel, customer, MAX(month) AS as_of_month FROM sellout_month GROUP BY ALL""")
    con.execute("""CREATE TABLE fact AS
        SELECT i.channel, i.customer, i.month, i.value AS sell_in, COALESCE(o.value, 0) AS sell_out
        FROM (SELECT channel, customer, month::DATE AS month, value FROM sellin) i
        JOIN last_seen a ON a.channel = i.channel AND a.customer = i.customer AND i.month <= a.as_of_month
        LEFT JOIN sellout_month o ON o.channel = i.channel AND o.customer = i.customer AND o.month = i.month""")
    return con


def query(sql):
    cur = build().execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def summary():
    return query("""
        SELECT f.channel, SUM(f.sell_in) AS sell_in, SUM(f.sell_out) AS sell_out,
               ANY_VALUE(t.target) AS target,
               ROUND(SUM(f.sell_out) * 1.0 / SUM(f.sell_in), 3)::DOUBLE AS sell_through,
               ROUND(SUM(f.sell_in) * 1.0 / ANY_VALUE(t.target), 3)::DOUBLE AS target_attainment
        FROM fact f
        JOIN (SELECT channel, SUM(value) AS target FROM target
              WHERE month::DATE <= (SELECT MAX(month) FROM fact) GROUP BY channel) t USING (channel)
        GROUP BY f.channel ORDER BY f.channel""")


def feeds():
    return query("""SELECT f.channel, f.customer, f.feed_type, a.as_of_month::VARCHAR AS as_of_month
                              FROM feed f JOIN last_seen a USING (channel, customer) ORDER BY 1, 2""")


def reconcile(rows, reference, threshold=0.001):
    """Fail loudly when a channel's sell-out drifts from an independent reference total."""
    for r in rows:
        ref = reference[r["channel"]]
        if abs(r["sell_out"] - ref) / ref > threshold:
            raise ValueError(f"{r['channel']}: sell-out {r['sell_out']} vs reference {ref}")


def load_reference():
    with open(D / "reference_totals.csv", newline="") as f:
        return {r["channel"]: float(r["sell_out"]) for r in csv.DictReader(f)}


@app.get("/api/summary")
def api_summary():
    return summary()


@app.get("/api/feeds")
def api_feeds():
    return feeds()


@app.get("/api/status")
def api_status():
    reconcile(summary(), load_reference())
    return {"reconciled": True}


@app.get("/")
def index():
    return FileResponse(HERE / "index.html")
