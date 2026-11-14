import csv

import pytest
from fastapi.testclient import TestClient

from app import D, app, build, load_reference, reconcile, summary

client = TestClient(app)


def truth():
    with open(D / "truth.csv", newline="") as f:
        return {(r["customer"], int(r["month"])): float(r["sell_out"]) for r in csv.DictReader(f)}


def test_feed_rules_reproduce_ground_truth_exactly():
    rows = build().execute("SELECT customer, month(month), sell_out FROM fact WHERE sell_out > 0").fetchall()
    assert {(c, m): v for c, m, v in rows} == truth()


def test_naive_sum_across_period_types_double_counts():
    naive = build().execute("SELECT SUM(value) FROM sellout").fetchone()[0]
    assert naive > sum(truth().values())  # retailer C reports the same sales twice


def test_sell_in_is_cut_at_sell_out_as_of_month():
    last = build().execute("SELECT MAX(month(month)) FROM fact WHERE customer = 'Retailer A'").fetchone()[0]
    assert last == 11


def test_gap_months_come_from_daily_rows():
    feed = dict(build().execute("SELECT customer, feed_type FROM feed").fetchall())
    assert feed["Retailer B"] == "monthly"
    months = {m for (c, m) in truth() if c == "Retailer B"}
    got = {m for (m,) in build().execute("SELECT month(month) FROM fact WHERE customer='Retailer B' AND sell_out > 0").fetchall()}
    assert got == months == set(range(1, 13))


def test_reconciliation_guard_passes_and_fails():
    reconcile(summary(), load_reference())
    drifted = [dict(r, sell_out=r["sell_out"] * 1.05) for r in summary()]
    with pytest.raises(ValueError):
        reconcile(drifted, load_reference())


def test_api_and_page_served():
    assert client.get("/api/summary").json() == summary()
    assert client.get("/api/status").json() == {"reconciled": True}
    assert len(client.get("/api/feeds").json()) == 4
    assert "Sell-in vs sell-out" in client.get("/").text
