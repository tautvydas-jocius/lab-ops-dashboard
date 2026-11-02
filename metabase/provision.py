"""Set up Metabase from scratch: admin user, warehouse connection, and four dashboards.

Idempotent enough for a demo: re-running replaces the dashboards (matched by name).
Usage: MB_ADMIN_PASSWORD=... python3 provision.py   (stdlib only)
"""
import json
import os
import time
import urllib.error
import urllib.request

MB = os.environ.get("MB_URL", "http://127.0.0.1:3300")
EMAIL = os.environ.get("MB_ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ["MB_ADMIN_PASSWORD"]
DB_PASSWORD = os.environ.get("DB_PASSWORD", "labops")
session = None


def api(method, path, body=None):
    req = urllib.request.Request(MB + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", **({"X-Metabase-Session": session} if session else {})},
                                 method=method)
    try:
        raw = urllib.request.urlopen(req, timeout=120).read()
        return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: {e.code} {e.read().decode()[:400]}")


for _ in range(90):  # Metabase takes ~1 min to boot
    try:
        if api("GET", "/api/health")["status"] == "ok":
            break
    except Exception:
        pass
    time.sleep(2)

props = api("GET", "/api/session/properties")
if props.get("setup-token") and not props.get("has-user-setup"):
    session = api("POST", "/api/setup", {
        "token": props["setup-token"],
        "user": {"email": EMAIL, "password": PASSWORD, "first_name": "Lab", "last_name": "Ops",
                 "site_name": "Lab Ops Analytics"},
        "prefs": {"site_name": "Lab Ops Analytics", "allow_tracking": False}})["id"]
else:
    session = api("POST", "/api/session", {"username": EMAIL, "password": PASSWORD})["id"]

dbs = api("GET", "/api/database")["data"]
db = next((d for d in dbs if d["name"] == "Lab Ops warehouse"), None)
if not db:
    db = api("POST", "/api/database", {"engine": "postgres", "name": "Lab Ops warehouse", "details": {
        "host": "db", "port": 5432, "dbname": "labops", "user": "labops", "password": DB_PASSWORD}})
DB = db["id"]

# --- dashboards: (title, [(card name, display, SQL, viz settings, width, height)]) -------------
def bar(x, *y, stacked=False, horizontal=False):
    s = {"graph.dimensions": [x] if isinstance(x, str) else x, "graph.metrics": list(y)}
    if stacked:
        s["stackable.stack_type"] = "stacked"
    return s


W = "WHERE {col} >= '2026-05-01'"  # report window; ERP warm-up purchases happen earlier
DASHBOARDS = [
    ("1 · ERP — procurement & lab stock", [
        ("Spend (EUR)", "scalar", "SELECT round(sum(spend_eur)) FROM analytics.po_performance " + W.format(col="order_date"), {}, 6, 3),
        ("Purchase price variance (EUR)", "scalar", "SELECT round(sum(ppv_eur)) FROM analytics.po_performance " + W.format(col="order_date"), {}, 6, 3),
        ("On-time delivery %", "scalar",
         "SELECT round(100.0 * avg(on_time::int), 1) FROM analytics.po_performance " + W.format(col="order_date") + " AND received_date IS NOT NULL", {}, 6, 3),
        ("Raw-material lots rejected by QC", "scalar", "SELECT count(*) FROM erp.stock_batches WHERE status = 'Rejected'", {}, 6, 3),
        ("Spend by material type and month", "bar",
         "SELECT date_trunc('month', order_date)::date AS month, material_type, round(sum(spend_eur)) AS spend_eur "
         "FROM analytics.po_performance " + W.format(col="order_date") + " GROUP BY 1, 2 ORDER BY 1",
         bar(["month", "material_type"], "spend_eur", stacked=True), 12, 7),
        ("Acetonitrile unit price vs standard (EUR/L)", "line",
         "SELECT order_date, unit_price_eur AS paid, standard_price_eur AS standard FROM analytics.po_performance "
         "WHERE material_id = 'L01' ORDER BY 1", bar("order_date", "paid", "standard"), 12, 7),
        ("Supplier scorecard", "table",
         "SELECT supplier, supplier_category AS category, count(*) AS po_lines, round(sum(spend_eur)) AS spend_eur, "
         "round(sum(ppv_eur)) AS ppv_eur, round(100.0 * avg(on_time::int)) AS otd_pct, "
         "round(avg(greatest(days_late, 0)), 1) AS avg_days_late, count(*) FILTER (WHERE batch_status = 'Rejected') AS lots_rejected "
         "FROM analytics.po_performance GROUP BY 1, 2 ORDER BY spend_eur DESC", {}, 12, 7),
        ("Lab stock batches by status", "row",
         "SELECT b.status, count(*) AS batches FROM erp.stock_batches b JOIN erp.materials m USING (material_id) "
         "GROUP BY 1 ORDER BY 2 DESC", bar("status", "batches"), 12, 7),
    ]),
    ("2 · LIMS — samples & quality", [
        ("Samples logged", "scalar", "SELECT count(*) FROM lims.samples", {}, 6, 3),
        ("Median release turnaround (h)", "scalar",
         "SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY tat_hours)::numeric) FROM analytics.sample_tat WHERE kind = 'Release'", {}, 6, 3),
        ("Out-of-spec results", "scalar", "SELECT count(*) FROM lims.analyses WHERE out_of_spec", {}, 6, 3),
        ("Open samples today", "scalar", "SELECT count(*) FROM lims.samples WHERE status <> 'verified'", {}, 6, 3),
        ("Samples logged per week, by ERP trigger", "bar",
         "SELECT date_trunc('week', logged_ts)::date AS week, kind, count(*) AS samples FROM analytics.sample_tat "
         + W.format(col="logged_ts") + " GROUP BY 1, 2 ORDER BY 1", bar(["week", "kind"], "samples", stacked=True), 12, 7),
        ("Median turnaround by month (h)", "line",
         "SELECT date_trunc('month', received_ts)::date AS month, kind, "
         "round(percentile_cont(0.5) WITHIN GROUP (ORDER BY tat_hours)::numeric) AS median_tat_h FROM analytics.sample_tat "
         + W.format(col="received_ts") + " AND tat_hours IS NOT NULL GROUP BY 1, 2 ORDER BY 1", bar(["month", "kind"], "median_tat_h"), 12, 7),
        ("Out-of-spec rate by test (%)", "row",
         "SELECT test, round(100.0 * avg(out_of_spec::int), 2) AS oos_pct FROM lims.analyses WHERE result IS NOT NULL "
         "GROUP BY 1 HAVING sum(out_of_spec::int) > 0 ORDER BY 2 DESC", bar("test", "oos_pct"), 12, 7),
        ("Incoming API assay by supplier lot", "scatter",
         "SELECT s.received_ts, a.result AS assay_pct, sp.name AS supplier FROM lims.analyses a JOIN lims.samples s USING (sample_id) "
         "JOIN erp.stock_batches b ON b.batch_id = s.trigger_ref JOIN erp.suppliers sp ON sp.supplier_id = b.supplier_id "
         "WHERE a.keyword = 'RM_ASSAY' AND s.material_id = 'M100' ORDER BY 1",
         bar(["received_ts", "supplier"], "assay_pct"), 12, 7),
    ]),
    ("3 · MES — test execution", [
        ("Test runs", "scalar", "SELECT count(*) FROM mes.executions", {}, 6, 3),
        ("Aborted runs", "scalar", "SELECT count(*) FROM mes.executions WHERE status <> 'Completed'", {}, 6, 3),
        ("Analyst hours", "scalar", "SELECT round(sum(analyst_minutes) / 60.0) FROM mes.executions", {}, 6, 3),
        ("Lab stock consumed (EUR)", "scalar", "SELECT round(sum(material_cost_eur)) FROM analytics.execution_cost", {}, 6, 3),
        ("Analyst hours per week by lab area", "bar",
         "SELECT date_trunc('week', e.start_ts)::date AS week, p.lab_area, round(sum(e.analyst_minutes) / 60.0) AS hours "
         "FROM mes.executions e JOIN mes.protocols p USING (keyword) " + W.format(col="e.start_ts")
         + " GROUP BY 1, 2 ORDER BY 1", bar(["week", "lab_area"], "hours", stacked=True), 12, 7),
        ("Runs per analyst per month", "bar",
         "SELECT date_trunc('month', start_ts)::date AS month, analyst, count(*) AS runs FROM mes.executions "
         + W.format(col="start_ts") + " GROUP BY 1, 2 ORDER BY 1", bar(["month", "analyst"], "runs"), 12, 7),
        ("Aborted runs by cause", "row",
         "SELECT status, keyword, count(*) AS runs FROM mes.executions WHERE status <> 'Completed' GROUP BY 1, 2 ORDER BY 3 DESC",
         bar(["status", "keyword"], "runs", stacked=True), 12, 7),
        ("Instrument hours by month", "bar",
         "SELECT date_trunc('month', start_ts)::date AS month, regexp_replace(instrument, '-0[0-9]$', '') AS instrument, "
         "round(sum(EXTRACT(EPOCH FROM end_ts - start_ts)) / 3600) AS hours FROM mes.executions "
         + W.format(col="start_ts") + " AND instrument NOT LIKE 'Incubator%' GROUP BY 1, 2 ORDER BY 1",
         bar(["month", "instrument"], "hours", stacked=True), 12, 7),
    ]),
    ("4 · Where the lab stalls", [
        ("Open analyses by state, end of each working day", "area",
         "SELECT day, state, open_analyses FROM lims.daily_wip " + W.format(col="day") + " ORDER BY 1",
         bar(["day", "state"], "open_analyses", stacked=True), 24, 8),
        ("Analysis-days lost by cause per month", "bar",
         "SELECT date_trunc('month', day)::date AS month, reason, count(*) AS analysis_days FROM lims.wait_events "
         + W.format(col="day") + " GROUP BY 1, 2 ORDER BY 1", bar(["month", "reason"], "analysis_days", stacked=True), 12, 7),
        ("Stock-outs: analysis-days waiting per material", "row",
         "SELECT m.name AS material, count(*) AS analysis_days FROM lims.wait_events w JOIN erp.materials m USING (material_id) "
         "WHERE reason = 'Waiting for stock' GROUP BY 1 ORDER BY 2 DESC", bar("material", "analysis_days"), 12, 7),
        ("Release turnaround vs open backlog, weekly", "line",
         "WITH t AS (SELECT date_trunc('week', received_ts)::date AS week, percentile_cont(0.5) WITHIN GROUP (ORDER BY tat_hours) AS tat "
         "FROM analytics.sample_tat WHERE kind = 'Release' AND tat_hours IS NOT NULL GROUP BY 1), "
         "b AS (SELECT date_trunc('week', day)::date AS week, avg(n) AS backlog FROM (SELECT day, sum(open_analyses) n "
         "FROM lims.daily_wip WHERE state IN ('Waiting for analyst', 'Waiting for stock', 'Repeat after aborted run') GROUP BY 1) x GROUP BY 1) "
         "SELECT week, round(tat::numeric) AS median_release_tat_h, round(backlog::numeric) AS queued_analyses FROM t JOIN b USING (week) "
         "WHERE week >= '2026-05-01' ORDER BY 1",
         dict(bar("week", "median_release_tat_h", "queued_analyses"),
              **{"series_settings": {"queued_analyses": {"axis": "right"}}}), 12, 7),
        ("The blocked TSA plate lot", "table",
         "SELECT u.batch_id, u.supplier_lot, u.supplier, u.batch_status, count(*) AS runs, "
         "count(*) FILTER (WHERE u.execution_status LIKE 'Aborted%') AS aborted, min(u.start_ts)::date AS first_use, "
         "max(u.start_ts)::date AS last_use FROM analytics.stock_usage u WHERE u.material = 'TSA plates' "
         "GROUP BY 1, 2, 3, 4 ORDER BY first_use", {}, 12, 7),
    ]),
    ("5 · Cost per test (ERP × MES × LIMS)", [
        ("Material cost per release sample (EUR)", "scalar",
         "SELECT round(avg(c), 2) FROM (SELECT e.sample_id, sum(material_cost_eur) c FROM analytics.execution_cost e "
         "JOIN lims.samples s USING (sample_id) WHERE s.plan_id LIKE 'SP-REL%' GROUP BY 1) x", {}, 8, 3),
        ("Cost of aborted runs (EUR)", "scalar",
         "SELECT round(sum(material_cost_eur)) FROM analytics.execution_cost WHERE status <> 'Completed'", {}, 8, 3),
        ("Expired or blocked stock written off (EUR)", "scalar",
         "SELECT round(sum(-mv.quantity * m.standard_price_eur)) FROM erp.inventory_movements mv JOIN erp.materials m USING (material_id) "
         "WHERE mv.movement_type = 'Expired write-off'", {}, 8, 3),
        ("Material cost per run by test (EUR)", "row",
         "SELECT keyword, round(avg(material_cost_eur), 2) AS eur_per_run FROM analytics.execution_cost "
         "GROUP BY 1 HAVING avg(material_cost_eur) > 0 ORDER BY 2 DESC", bar("keyword", "eur_per_run"), 12, 7),
        ("Monthly lab material cost by material", "bar",
         "SELECT date_trunc('month', start_ts)::date AS month, material, round(sum(cost_eur)) AS eur FROM analytics.stock_usage "
         + W.format(col="start_ts") + " GROUP BY 1, 2 ORDER BY 1", bar(["month", "material"], "eur", stacked=True), 12, 7),
        ("Cost per sample by sampling plan", "table",
         "SELECT s.plan_id, count(DISTINCT s.sample_id) AS samples, round(sum(e.material_cost_eur) / count(DISTINCT s.sample_id), 2) AS material_eur_per_sample, "
         "round(sum(e.analyst_minutes)::numeric / count(DISTINCT s.sample_id)) AS analyst_min_per_sample "
         "FROM lims.samples s JOIN analytics.execution_cost e USING (sample_id) GROUP BY 1 ORDER BY 3 DESC", {}, 24, 6),
    ]),
]

for d in api("GET", "/api/dashboard"):  # replace every dashboard this script owns (digit-prefixed names)
    if d["name"][0].isdigit():
        api("DELETE", f"/api/dashboard/{d['id']}")
for title, cards in DASHBOARDS:
    dash = api("POST", "/api/dashboard", {"name": title, "width": "full"})
    dashcards, row, col = [], 0, 0
    for i, (name, display, sql, viz, w, h) in enumerate(cards):
        card = api("POST", "/api/card", {
            "name": name, "display": display, "visualization_settings": viz,
            "dataset_query": {"type": "native", "native": {"query": sql}, "database": DB}})
        if col + w > 24:
            row, col = row + prev_h, 0
        dashcards.append({"id": -(i + 1), "card_id": card["id"], "row": row, "col": col, "size_x": w, "size_y": h})
        col, prev_h = col + w, h
    api("PUT", f"/api/dashboard/{dash['id']}", {"dashcards": dashcards})
    print(f"{title}: {MB}/dashboard/{dash['id']}")
