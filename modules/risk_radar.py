from datetime import date, timedelta

from database import get_conn

GROUPS = ["O+", "B+", "A+", "AB+", "O-", "B-", "A-", "AB-"]
PRODUCTS = ["PRBC", "Platelets"]
TARGET_DAYS = {"PRBC": 7, "Platelets": 3}
EXPIRY_WINDOW = {"PRBC": 7, "Platelets": 2}


def _demand(conn, today, days):
    start = (today - timedelta(days=days)).isoformat()
    out = {}
    for g, p, n in conn.execute(
            "SELECT blood_group, product, SUM(units_needed) FROM requests "
            "WHERE request_date >= ? GROUP BY blood_group, product", (start,)):
        out[(g, p)] = n or 0
    return out


def compute(surge=1.0):
    today = date.today()
    conn = get_conn()
    d7 = _demand(conn, today, 7)
    d30 = _demand(conn, today, 30)

    stock, soon = {}, {}
    for g, p, exp in conn.execute(
            "SELECT blood_group, product, expiry_date FROM blood_units "
            "WHERE status='in_stock' AND expiry_date >= ?", (today.isoformat(),)):
        left = (date.fromisoformat(exp) - today).days
        stock[(g, p)] = stock.get((g, p), 0) + 1
        if left <= EXPIRY_WINDOW[p]:
            soon[(g, p)] = soon.get((g, p), 0) + 1

    start90 = (today - timedelta(days=90)).isoformat()
    wast = {}
    for p, s, n in conn.execute(
            "SELECT product, status, COUNT(*) FROM blood_units "
            "WHERE status IN ('used','expired') AND status_date >= ? "
            "GROUP BY product, status", (start90,)):
        wast.setdefault(p, {"used": 0, "expired": 0})[s] = n
    conn.close()

    rows = []
    for p in PRODUCTS:
        for g in GROUPS:
            n7 = d7.get((g, p), 0) / 7
            n30 = d30.get((g, p), 0) / 30
            demand = (0.5 * n7 + 0.5 * n30) * surge
            st = stock.get((g, p), 0)
            cover = st / demand if demand > 0 else 99.0
            cover = min(cover, 99.0)
            if cover >= 99.0:
                risk = 0
            else:
                risk = max(0, min(100, round(100 * (1 - cover / TARGET_DAYS[p]))))
            level = "HIGH" if risk >= 70 else "MEDIUM" if risk >= 35 else "LOW"
            sn = soon.get((g, p), 0)
            expected_use = demand * EXPIRY_WINDOW[p]
            at_risk = max(0, sn - round(expected_use))
            exp_pct = round(100 * at_risk / sn) if sn else 0
            rows.append({
                "group": g, "product": p, "stock": st,
                "demand": round(demand, 2), "cover": round(cover, 1),
                "risk_pct": risk, "level": level,
                "expiring": sn, "at_risk": at_risk, "exp_pct": exp_pct,
                "window": EXPIRY_WINDOW[p],
            })

    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in rows:
        counts[r["level"]] += 1

    spikes = {}
    for p in PRODUCTS:
        s7 = sum(v for (g, pp), v in d7.items() if pp == p) / 7
        s30 = sum(v for (g, pp), v in d30.items() if pp == p) / 30
        spikes[p] = round(s7 / s30, 2) if s30 else 1.0

    actions = []
    for r in sorted(rows, key=lambda r: -r["risk_pct"]):
        if r["level"] == "HIGH":
            actions.append(
                f"Arrange {r['group']} {r['product']} collection: stock of "
                f"{r['stock']} units covers only {r['cover']} days.")
    for r in sorted(rows, key=lambda r: -r["at_risk"]):
        if r["at_risk"] >= 2:
            actions.append(
                f"Use or transfer {r['at_risk']} {r['group']} {r['product']} units "
                f"expiring within {r['window']} days.")
    for p, s in spikes.items():
        if s >= 1.3:
            actions.append(
                f"Prepare for a {p} demand spike: the last 7 days are "
                f"{round((s - 1) * 100)}% above the 30-day average.")
    if not actions:
        actions.append("No urgent action. Stock looks healthy for the next few days.")

    wastage = []
    for p in PRODUCTS:
        u = wast.get(p, {}).get("used", 0)
        e = wast.get(p, {}).get("expired", 0)
        wastage.append({"product": p, "used": u, "expired": e,
                        "rate": round(100 * e / (u + e), 1) if (u + e) else 0})

    lookup = {(r["group"], r["product"]): r["risk_pct"] for r in rows}
    chart = {p: [lookup[(g, p)] for g in GROUPS] for p in PRODUCTS}

    return {
        "today": today.isoformat(),
        "rows": sorted(rows, key=lambda r: (-r["risk_pct"], r["stock"])),
        "counts": counts, "actions": actions[:6], "spikes": spikes,
        "wastage": wastage, "groups": GROUPS, "chart": chart,
    }
