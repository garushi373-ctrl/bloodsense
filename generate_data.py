import random
from datetime import date, datetime, time, timedelta
from database import init_db, get_conn

random.seed(42)

GROUPS = ["O+", "B+", "A+", "AB+", "O-", "B-", "A-", "AB-"]
WEIGHTS = [36, 31, 21, 7, 2, 1.5, 1, 0.5]
AREAS = ["Area A", "Area B", "Area C", "Area D", "Area E"]
SHELF = {"PRBC": 35, "Platelets": 5}
MEAN_USE = {"PRBC": 14, "Platelets": 3.0}
DAYS = 730


def season_factor(d):
    return 1.5 if d.month in (8, 9, 10) else 1.0


def delay(base, d, weekend_boost=False):
    m = random.gauss(base, base * 0.25)
    if weekend_boost and d.weekday() >= 5:
        m *= 2.5
    if random.random() < 0.05:
        m *= 3
    return max(10, m)


def main():
    init_db()
    conn = get_conn()
    cur = conn.cursor()
    for t in ("stage_events", "blood_units", "requests", "camps", "donors"):
        cur.execute(f"DELETE FROM {t}")

    donors = [(i, random.choices(GROUPS, WEIGHTS)[0], random.choice(AREAS), None)
              for i in range(1, 401)]
    cur.executemany("INSERT INTO donors VALUES (?,?,?,?)", donors)

    today = date.today()
    start = today - timedelta(days=DAYS)
    units, events, requests, camps = [], [], [], []
    unit_id = event_id = 0

    for k in range(DAYS):
        d = start + timedelta(days=k)

        n = random.randint(12, 22)
        if d.weekday() >= 5:
            n = int(n * 0.7)
        for _ in range(n):
            donor = random.choice(donors)
            for product in ("PRBC", "Platelets"):
                if product == "Platelets" and random.random() > 0.4:
                    continue
                unit_id += 1
                shelf = SHELF[product]
                mean = MEAN_USE[product]
                if product == "Platelets" and d.weekday() >= 4:
                    mean *= 1.8
                used_after = random.expovariate(1 / mean)
                if used_after > shelf:
                    status, sdate = "expired", d + timedelta(days=shelf)
                else:
                    status, sdate = "used", d + timedelta(days=int(used_after))
                if sdate > today:
                    status, sdate = "in_stock", None
                units.append((unit_id, donor[0], donor[1], product, d.isoformat(),
                              (d + timedelta(days=shelf)).isoformat(), status,
                              sdate.isoformat() if sdate else None))

                t = datetime.combine(d, time(random.randint(9, 16), random.randint(0, 59)))
                steps = [("Collection", 0), ("Testing", delay(90, d, True)),
                         ("Separation", delay(120, d)), ("Storage", delay(45, d))]
                for stage, mins in steps:
                    t += timedelta(minutes=mins)
                    event_id += 1
                    events.append((event_id, unit_id, stage, t.strftime("%Y-%m-%d %H:%M:%S")))

        for _ in range(int(random.randint(5, 10) * season_factor(d))):
            requests.append((None, d.isoformat(), random.choices(GROUPS, WEIGHTS)[0],
                             random.choices(["PRBC", "Platelets"], [75, 25])[0],
                             random.randint(1, 3), random.choice(AREAS),
                             random.choices(["Routine", "Urgent", "Emergency"], [70, 22, 8])[0]))

        if k % 10 == 0:
            hour = random.choice([10, 12, 16])
            holiday = 1 if d.weekday() == 6 or random.random() < 0.05 else 0
            registered = random.randint(60, 200)
            rate = 0.55
            if hour == 10 and d.weekday() < 5:
                rate *= 0.7
            if hour == 16:
                rate *= 1.1
            if holiday:
                rate *= 0.8
            turnout = int(registered * rate * random.uniform(0.85, 1.15))
            camps.append((None, d.isoformat(), random.choice(AREAS), hour,
                          d.weekday(), holiday, registered, turnout))

    cur.executemany("INSERT INTO blood_units VALUES (?,?,?,?,?,?,?,?)", units)
    cur.executemany("INSERT INTO stage_events VALUES (?,?,?,?)", events)
    cur.executemany("INSERT INTO requests VALUES (?,?,?,?,?,?,?)", requests)
    cur.executemany("INSERT INTO camps VALUES (?,?,?,?,?,?,?,?)", camps)
    conn.commit()
    conn.close()
    print(f"Done: {len(units)} units, {len(events)} events, "
          f"{len(requests)} requests, {len(camps)} camps")


if __name__ == "__main__":
    main()
