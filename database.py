import os
import sqlite3

DB_PATH = os.path.join("data", "bloodsense.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS donors (
    donor_id INTEGER PRIMARY KEY,
    blood_group TEXT NOT NULL,
    area TEXT,
    last_donation DATE
);
CREATE TABLE IF NOT EXISTS blood_units (
    unit_id INTEGER PRIMARY KEY,
    donor_id INTEGER,
    blood_group TEXT NOT NULL,
    product TEXT NOT NULL,
    collected_on DATE NOT NULL,
    expiry_date DATE NOT NULL,
    status TEXT NOT NULL,
    status_date DATE,
    FOREIGN KEY (donor_id) REFERENCES donors(donor_id)
);
CREATE TABLE IF NOT EXISTS stage_events (
    event_id INTEGER PRIMARY KEY,
    unit_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    FOREIGN KEY (unit_id) REFERENCES blood_units(unit_id)
);
CREATE TABLE IF NOT EXISTS requests (
    request_id INTEGER PRIMARY KEY,
    request_date DATE NOT NULL,
    blood_group TEXT NOT NULL,
    product TEXT NOT NULL,
    units_needed INTEGER NOT NULL,
    area TEXT,
    urgency TEXT
);
CREATE TABLE IF NOT EXISTS camps (
    camp_id INTEGER PRIMARY KEY,
    camp_date DATE NOT NULL,
    area TEXT NOT NULL,
    start_hour INTEGER,
    weekday INTEGER,
    holiday INTEGER,
    registered INTEGER,
    turnout INTEGER
);
"""

def get_conn():
    os.makedirs("data", exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database ready:", DB_PATH)
