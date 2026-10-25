import io
from datetime import date, datetime, timedelta

import pandas as pd
import qrcode

from database import get_conn

STAGES = ["Collection", "Testing", "Separation", "Storage"]
PAIRS = [(STAGES[i], STAGES[i + 1]) for i in range(len(STAGES) - 1)]
COLS = [f"{a} -> {b}" for a, b in PAIRS]
Z_LIMIT = 2.0
FMT = "%Y-%m-%d %H:%M:%S"


def load_durations():
    conn = get_conn()
    ev = pd.read_sql_query("SELECT unit_id, stage, timestamp FROM stage_events", conn)
    units = pd.read_sql_query(
        "SELECT unit_id, blood_group, product, collected_on FROM blood_units", conn)
    conn.close()
    ev["timestamp"] = pd.to_datetime(ev["timestamp"])
    wide = ev.groupby(["unit_id", "stage"])["timestamp"].max().unstack()
    for s in STAGES:
        if s not in wide.columns:
            wide[s] = pd.NaT
    out = pd.DataFrame(index=wide.index)
    for (a, b), col in zip(PAIRS, COLS):
        out[col] = (wide[b] - wide[a]).dt.total_seconds() / 60
    out = out.reset_index().merge(units, on="unit_id")
    out["weekend"] = pd.to_datetime(out["collected_on"]).dt.weekday >= 5
    return out


def get_stats(df):
    return {c: (float(df[c].mean()), float(df[c].std())) for c in COLS}


def summary():
    df = load_durations()
    stats = get_stats(df)
    rows = []
    for c in COLS:
        m, s = stats[c]
        z = (df[c] - m) / s
        valid = int(df[c].notna().sum())
        delayed = int((z > Z_LIMIT).sum())
        rows.append({
            "pair": c,
            "mean": round(m, 1),
            "limit": round(m + Z_LIMIT * s, 1),
            "delayed": delayed,
            "delayed_pct": round(100 * delayed / max(valid, 1), 1),
            "weekday_mean": round(float(df.loc[~df["weekend"], c].mean()), 1),
            "weekend_mean": round(float(df.loc[df["weekend"], c].mean()), 1),
        })
    return rows


def worst_units(limit=15):
    df = load_durations()
    stats = get_stats(df)
    zs = pd.DataFrame({c: (df[c] - stats[c][0]) / stats[c][1] for c in COLS}).fillna(-999)
    df["max_z"] = zs.max(axis=1)
    df["worst_pair"] = zs.idxmax(axis=1)
    out = []
    for _, r in df.sort_values("max_z", ascending=False).head(limit).iterrows():
        c = r["worst_pair"]
        out.append({
            "unit_id": int(r["unit_id"]),
            "blood_group": r["blood_group"],
            "product": r["product"],
            "pair": c,
            "minutes": float(r[c]),
            "normal": stats[c][0],
        })
    return out


def unit_report(unit_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT unit_id, blood_group, product, collected_on, expiry_date, status "
        "FROM blood_units WHERE unit_id=?", (unit_id,)).fetchone()
    events = conn.execute(
        "SELECT stage, timestamp FROM stage_events WHERE unit_id=? ORDER BY timestamp",
        (unit_id,)).fetchall()
    conn.close()
    if row is None:
        return None
    unit = dict(zip(["unit_id", "blood_group", "product", "collected_on",
                     "expiry_date", "status"], row))
    stats = get_stats(load_durations())
    ts = {s: datetime.strptime(t, FMT) for s, t in events}
    steps = []
    for (a, b), c in zip(PAIRS, COLS):
        if a in ts and b in ts:
            mins = (ts[b] - ts[a]).total_seconds() / 60
            m, s = stats[c]
            z = (mins - m) / s
            steps.append({"pair": c, "minutes": mins, "normal": m,
                          "z": round(z, 1), "delayed": z > Z_LIMIT})
    next_stage = next((s for s in STAGES if s not in ts), None)
    return {"u": unit, "events": events, "steps": steps, "next_stage": next_stage}


def create_unit(blood_group, product):
    shelf = 35 if product == "PRBC" else 5
    today = date.today()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO blood_units (donor_id, blood_group, product, collected_on, "
        "expiry_date, status, status_date) VALUES (NULL, ?, ?, ?, ?, 'in_stock', NULL)",
        (blood_group, product, today.isoformat(),
         (today + timedelta(days=shelf)).isoformat()))
    uid = cur.lastrowid
    cur.execute("INSERT INTO stage_events (unit_id, stage, timestamp) VALUES (?, ?, ?)",
                (uid, "Collection", datetime.now().strftime(FMT)))
    conn.commit()
    conn.close()
    return uid


def record_stage(unit_id, demo_minutes=None):
    conn = get_conn()
    rows = conn.execute("SELECT stage, timestamp FROM stage_events WHERE unit_id=?",
                        (unit_id,)).fetchall()
    done = {s: datetime.strptime(t, FMT) for s, t in rows}
    nxt = next((s for s in STAGES if s not in done), None)
    if nxt is None:
        conn.close()
        return None
    idx = STAGES.index(nxt)
    if demo_minutes is not None and idx > 0:
        when = done[STAGES[idx - 1]] + timedelta(minutes=demo_minutes)
    else:
        when = datetime.now()
    conn.execute("INSERT INTO stage_events (unit_id, stage, timestamp) VALUES (?, ?, ?)",
                 (unit_id, nxt, when.strftime(FMT)))
    conn.commit()
    conn.close()
    return nxt


def qr_png(url):
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    return buf
