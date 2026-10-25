from datetime import date, timedelta

import numpy as np

from database import get_conn

GROUPS = ["O+", "B+", "A+", "AB+", "O-", "B-", "A-", "AB-"]
SHELF = {"PRBC": 35, "Platelets": 5}
FRIDGES = 4
RUNS = 1000


def baseline_inputs(group, product):
    """Current stock by days-left, average daily donations and demand."""
    today = date.today()
    shelf = SHELF[product]
    conn = get_conn()
    gcond = "" if group == "All" else " AND blood_group=?"
    gargs = () if group == "All" else (group,)

    stock = np.zeros(shelf + 1)
    for exp, n in conn.execute(
            "SELECT expiry_date, COUNT(*) FROM blood_units WHERE status='in_stock' "
            "AND product=? AND expiry_date >= ?" + gcond + " GROUP BY expiry_date",
            (product, today.isoformat()) + gargs):
        left = (date.fromisoformat(exp) - today).days
        if 0 <= left <= shelf:
            stock[left] += n

    d60 = (today - timedelta(days=60)).isoformat()
    don = conn.execute(
        "SELECT COUNT(*) FROM blood_units WHERE product=? AND collected_on >= ?" + gcond,
        (product, d60) + gargs).fetchone()[0] / 60.0
    d30 = (today - timedelta(days=30)).isoformat()
    dem = (conn.execute(
        "SELECT SUM(units_needed) FROM requests WHERE product=? AND request_date >= ?" + gcond,
        (product, d30) + gargs).fetchone()[0] or 0) / 30.0
    conn.close()
    return stock, don, dem


def simulate(stock0, don_mean, dem_mean, horizon, fridges_down=0, seed=42):
    rng = np.random.default_rng(seed)
    shelf = len(stock0) - 1
    keep = max(0.0, 1.0 - fridges_down / FRIDGES)
    bucket = np.tile(np.floor(stock0 * keep), (RUNS, 1))

    stock_t = np.zeros((horizon, RUNS))
    short_flag = np.zeros(RUNS, dtype=bool)
    short_by_day = np.zeros(horizon)
    expired = np.zeros(RUNS)
    unmet_total = np.zeros(RUNS)

    for t in range(horizon):
        expired += bucket[:, 0]
        bucket[:, :-1] = bucket[:, 1:]
        bucket[:, -1] = 0
        bucket[:, shelf] += rng.poisson(don_mean, RUNS)
        remaining = rng.poisson(dem_mean, RUNS).astype(float)
        for k in range(shelf + 1):
            take = np.minimum(bucket[:, k], remaining)
            bucket[:, k] -= take
            remaining -= take
        unmet_total += remaining
        short_flag |= remaining > 0
        short_by_day[t] = short_flag.mean()
        stock_t[t] = bucket.sum(axis=1)

    p50_day = next((i + 1 for i, v in enumerate(short_by_day) if v >= 0.5), None)
    return {
        "mean": [round(float(v), 1) for v in stock_t.mean(axis=1)],
        "p10": [round(float(v), 1) for v in np.percentile(stock_t, 10, axis=1)],
        "p90": [round(float(v), 1) for v in np.percentile(stock_t, 90, axis=1)],
        "short": [round(100 * float(v), 1) for v in short_by_day],
        "short_end": round(100 * float(short_by_day[-1]), 1),
        "p50_day": p50_day,
        "expired": round(float(expired.mean()), 1),
        "unmet": round(float(unmet_total.mean()), 1),
        "end_stock": round(float(stock_t[-1].mean()), 1),
    }


def run(group, product, horizon, don_change, dem_change, fridges_down):
    stock0, don, dem = baseline_inputs(group, product)
    base = simulate(stock0, don, dem, horizon, 0)
    scen = simulate(stock0, don * (1 + don_change / 100.0),
                    dem * (1 + dem_change / 100.0), horizon, fridges_down)
    today = date.today()
    labels = [(today + timedelta(days=i + 1)).strftime("%d %b") for i in range(horizon)]
    return {
        "labels": labels, "base": base, "scen": scen,
        "stock_now": int(stock0.sum()), "don": round(don, 1), "dem": round(dem, 1),
        "don_s": round(don * (1 + don_change / 100.0), 1),
        "dem_s": round(dem * (1 + dem_change / 100.0), 1),
        "shortage_date": (labels[scen["p50_day"] - 1] if scen["p50_day"] else None),
        "base_date": (labels[base["p50_day"] - 1] if base["p50_day"] else None),
    }
