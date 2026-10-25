import math
from datetime import date, timedelta

import numpy as np

from database import get_conn

GROUPS = ["O+", "B+", "A+", "AB+", "O-", "B-", "A-", "AB-"]

# Edit these with real locations of your areas and blood banks.
AREAS = {
    "Area A": (18.5400, 73.8700),
    "Area B": (18.6000, 73.8000),
    "Area C": (18.4400, 73.9500),
    "Area D": (18.2500, 73.7000),
    "Area E": (18.7500, 74.1500),
}
BANKS = [
    ("Central Blood Bank", 18.5204, 73.8567),
]

HOURS = [(10, "10 AM"), (12, "12 PM"), (16, "4 PM")]
LOW_RATE = 0.40          # turnout below 40% of registered donors = low turnout
DESERT_KM = 25
POOR_KM = 12


def km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _features(hour, weekday, holiday):
    return [1.0,
            1.0 if (hour == 10 and weekday < 5) else 0.0,
            1.0 if hour == 16 else 0.0,
            1.0 if holiday else 0.0]


def fit_model():
    conn = get_conn()
    rows = conn.execute(
        "SELECT start_hour, weekday, holiday, registered, turnout FROM camps "
        "WHERE registered > 0").fetchall()
    conn.close()
    X = np.array([_features(h, w, ho) for h, w, ho, r, t in rows])
    y = np.array([t / r for h, w, ho, r, t in rows])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    sigma = float(resid.std(ddof=min(len(y) - 1, X.shape[1]))) if len(y) > 5 else 0.1
    return coef, max(sigma, 0.03), len(rows)


def predict_rate(coef, hour, weekday, holiday):
    r = float(np.dot(coef, _features(hour, weekday, holiday)))
    return min(max(r, 0.05), 0.95)


def p_low(rate, sigma):
    z = (LOW_RATE - rate) / sigma
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def area_table():
    today = date.today()
    conn = get_conn()
    start = (today - timedelta(days=90)).isoformat()
    demand = dict(conn.execute(
        "SELECT area, SUM(units_needed) FROM requests WHERE request_date >= ? "
        "GROUP BY area", (start,)).fetchall())
    emergency = dict(conn.execute(
        "SELECT area, COUNT(*) FROM requests WHERE request_date >= ? "
        "AND urgency='Emergency' GROUP BY area", (start,)).fetchall())
    last_camp = dict(conn.execute(
        "SELECT area, MAX(camp_date) FROM camps GROUP BY area").fetchall())
    conn.close()

    rows = []
    for name, (lat, lon) in AREAS.items():
        dist = min(km(lat, lon, b[1], b[2]) for b in BANKS)
        per_day = (demand.get(name, 0) or 0) / 90.0
        lc = last_camp.get(name)
        since = (today - date.fromisoformat(lc)).days if lc else 365
        if dist >= DESERT_KM:
            level = "BLOOD ACCESS DESERT"
        elif dist >= POOR_KM:
            level = "Poor access"
        else:
            level = "Good access"
        score = per_day * (1 + dist / 10.0) * (1 + min(since, 180) / 60.0)
        rows.append({
            "area": name, "lat": lat, "lon": lon, "dist": round(dist, 1),
            "per_day": round(per_day, 2), "emergency": emergency.get(name, 0),
            "since": since, "level": level, "score": round(score, 2),
        })
    rows.sort(key=lambda r: -r["score"])
    return rows


def demand_by_group(area, expected_turnout):
    today = date.today()
    start = (today - timedelta(days=180)).isoformat()
    conn = get_conn()
    need = dict(conn.execute(
        "SELECT blood_group, SUM(units_needed) FROM requests WHERE area=? "
        "AND request_date >= ? GROUP BY blood_group", (area, start)).fetchall())
    donors = dict(conn.execute(
        "SELECT blood_group, COUNT(*) FROM donors WHERE area=? GROUP BY blood_group",
        (area,)).fetchall())
    conn.close()
    total_need = sum(need.values()) or 1
    total_don = sum(donors.values()) or 1
    out = []
    for g in GROUPS:
        share = 100.0 * need.get(g, 0) / total_need
        level = ("High" if share >= 25 else "Medium" if share >= 10
                 else "Low" if share >= 3 else "Very low")
        out.append({
            "group": g, "units": need.get(g, 0), "share": round(share, 1),
            "level": level,
            "expected_donors": round(expected_turnout * donors.get(g, 0) / total_don),
        })
    return out


def plan(area, camp_date, registered, holiday):
    coef, sigma, n = fit_model()
    weekday = camp_date.weekday()
    hol = bool(holiday) or weekday == 6
    options = []
    for hour, label in HOURS:
        rate = predict_rate(coef, hour, weekday, hol)
        options.append({
            "hour": hour, "label": label, "rate": round(100 * rate),
            "turnout": round(registered * rate),
            "p_low": round(100 * p_low(rate, sigma)),
        })
    best = max(options, key=lambda o: o["turnout"])
    return {
        "options": options, "best": best, "n": n, "weekday": weekday,
        "holiday": hol, "sigma": round(sigma, 3),
        "coef": [round(float(c), 3) for c in coef],
    }
