"""Synthetic sell-in, sell-out (mixed period types), target and ground truth for a fictional manufacturer.

Four customers, four reporting situations:
  Retailer A       monthly feed, last month is 11 (reports lag behind sell-in)
  Retailer B       monthly feed months 1-9, then only daily rows for 10-12 (gap months)
  Retailer C       the same sales reported twice: monthly AND daily for all 12 months (double-count trap)
  Marketplace X    daily feed only
"""
import calendar
import csv
from pathlib import Path

import numpy as np

rng = np.random.default_rng(21)
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)
YEAR = 2025
CUSTOMERS = [("Modern Trade", "Retailer A"), ("Modern Trade", "Retailer B"),
             ("Modern Trade", "Retailer C"), ("E-commerce", "Marketplace X")]
LAST_MONTH = {"Retailer A": 11}


def daily_split(total, month):
    days = calendar.monthrange(YEAR, month)[1]
    vals = [total // days] * days
    vals[0] += total - sum(vals)  # the remainder keeps the monthly sum exact
    return [(f"{YEAR}-{month:02d}-{d + 1:02d}", v) for d, v in enumerate(vals)]


truth = {}      # (customer, month) -> sell-out value actually in the comparison window
sellout_rows, sellin_rows = [], []
for ch, cu in CUSTOMERS:
    for m in range(1, 13):
        so = int(rng.integers(8_000, 20_000))
        sellin_rows.append((f"{YEAR}-{m:02d}-01", ch, cu, int(so * rng.uniform(0.9, 1.3))))
        if m > LAST_MONTH.get(cu, 12):
            continue
        truth[cu, m] = so
        monthly = (cu == "Retailer A") or (cu == "Retailer B" and m <= 9) or cu == "Retailer C"
        daily = (cu == "Retailer B" and m >= 10) or cu == "Retailer C" or cu == "Marketplace X"
        if monthly:
            sellout_rows.append(("monthly", f"{YEAR}-{m:02d}-01", ch, cu, so))
        if daily:
            sellout_rows += [("daily", d, ch, cu, v) for d, v in daily_split(so, m)]


def write(name, header, rows):
    with open(OUT / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


write("sellout.csv", ["period_type", "period_start", "channel", "customer", "value"], sellout_rows)
write("sellin.csv", ["month", "channel", "customer", "value"], sellin_rows)
write("target.csv", ["month", "channel", "value"],
      [(f"{YEAR}-{m:02d}-01", ch, int(sum(r[3] for r in sellin_rows if r[1] == ch and r[0].endswith(f"-{m:02d}-01")) * 1.1))
       for ch in ("Modern Trade", "E-commerce") for m in range(1, 13)])
# independent reference total per channel, stands in for a reference workbook
ref = {}
for (cu, m), v in truth.items():
    ch = next(c for c, k in CUSTOMERS if k == cu)
    ref[ch] = ref.get(ch, 0) + v
write("reference_totals.csv", ["channel", "sell_out"], sorted(ref.items()))
write("truth.csv", ["customer", "month", "sell_out"], [(cu, m, v) for (cu, m), v in sorted(truth.items())])
print("wrote", OUT)
