import sys
from datetime import date, timedelta

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from modules import black_box as bb
from modules import camp_planner as cp
from modules import risk_radar as rr
from modules import simulator as sim

app = Flask(__name__)
GROUPS = ["O+", "B+", "A+", "AB+", "O-", "B-", "A-", "AB-"]


def _int(name, default, lo, hi):
    try:
        v = int(float(request.args.get(name, default)))
    except ValueError:
        v = default
    return min(max(v, lo), hi)


@app.template_filter("hm")
def hm(minutes):
    try:
        minutes = int(round(float(minutes)))
    except (TypeError, ValueError):
        return "-"
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


@app.route("/")
def home():
    return redirect(url_for("risk"))


@app.route("/risk")
def risk():
    try:
        surge = float(request.args.get("surge", "1"))
    except ValueError:
        surge = 1.0
    surge = min(max(surge, 0.5), 3.0)
    data = rr.compute(surge)
    bottleneck = max(bb.summary(), key=lambda r: r["delayed_pct"])
    return render_template("risk.html", surge=surge, bottleneck=bottleneck, **data)


@app.route("/camp")
def camp():
    areas = cp.area_table()
    area = request.args.get("area", areas[0]["area"])
    if area not in cp.AREAS:
        area = areas[0]["area"]
    try:
        d = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        d = date.today() + timedelta(days=7)
    registered = _int("registered", 120, 10, 2000)
    hour = _int("hour", 10, 10, 16)
    if hour not in (10, 12, 16):
        hour = 10
    holiday = request.args.get("holiday") == "1"
    pl = cp.plan(area, d, registered, holiday)
    planned = next(o for o in pl["options"] if o["hour"] == hour)
    groups = cp.demand_by_group(area, planned["turnout"])
    return render_template("camp.html", areas=areas, area=area, date_str=d.isoformat(),
                           registered=registered, hour=hour, holiday=holiday,
                           plan=pl, planned=planned, best=pl["best"], groups=groups,
                           banks=cp.BANKS)


@app.route("/whatif")
def whatif():
    group = request.args.get("group", "All")
    if group not in GROUPS:
        group = "All"
    product = request.args.get("product", "PRBC")
    if product not in ("PRBC", "Platelets"):
        product = "PRBC"
    horizon = _int("horizon", 30, 7, 60)
    don = _int("don", 0, -60, 60)
    dem = _int("dem", 0, -50, 100)
    fridges = _int("fridges", 0, 0, 3)
    r = sim.run(group, product, horizon, don, dem, fridges)
    return render_template("whatif.html", r=r, group=group, product=product,
                           horizon=horizon, don=don, dem=dem, fridges=fridges,
                           groups=GROUPS)


@app.route("/blackbox")
def blackbox():
    return render_template("blackbox.html", rows=bb.summary(),
                           worst=bb.worst_units(), groups=GROUPS)


@app.route("/blackbox/go")
def blackbox_go():
    try:
        uid = int(request.args.get("unit_id", ""))
    except ValueError:
        return redirect(url_for("blackbox"))
    return redirect(url_for("unit", unit_id=uid))


@app.route("/unit/<int:unit_id>")
def unit(unit_id):
    rep = bb.unit_report(unit_id)
    if rep is None:
        abort(404)
    return render_template("unit.html",
                           scan_url=request.host_url + f"unit/{unit_id}", **rep)


@app.route("/unit/<int:unit_id>/qr.png")
def unit_qr(unit_id):
    return send_file(bb.qr_png(request.host_url + f"unit/{unit_id}"),
                     mimetype="image/png")


@app.route("/unit/new", methods=["POST"])
def unit_new():
    group = request.form.get("blood_group", "O+")
    product = request.form.get("product", "PRBC")
    if group not in GROUPS or product not in ("PRBC", "Platelets"):
        abort(400)
    return redirect(url_for("unit", unit_id=bb.create_unit(group, product)))


@app.route("/unit/<int:unit_id>/stage", methods=["POST"])
def unit_stage(unit_id):
    if bb.unit_report(unit_id) is None:
        abort(404)
    raw = request.form.get("demo_minutes", "").strip()
    try:
        minutes = float(raw) if raw else None
    except ValueError:
        minutes = None
    bb.record_stage(unit_id, minutes)
    return redirect(url_for("unit", unit_id=unit_id))


if __name__ == "__main__":
    lan = "--lan" in sys.argv
    app.run(host="0.0.0.0" if lan else "127.0.0.1", debug=not lan)
