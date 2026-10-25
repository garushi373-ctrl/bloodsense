import sys

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from modules import black_box as bb

app = Flask(__name__)
GROUPS = ["O+", "B+", "A+", "AB+", "O-", "B-", "A-", "AB-"]


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
    return redirect(url_for("blackbox"))


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
