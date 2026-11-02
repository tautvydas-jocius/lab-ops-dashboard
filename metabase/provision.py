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


DASHBOARDS = [
    ("1 · Procurement", [
        ("Spend (EUR)", "scalar", "SELECT round(sum(spend_eur)) AS spend FROM analytics.po_performance", {}, 6, 3),
        ("Purchase price variance (EUR)", "scalar", "SELECT round(sum(ppv_eur)) AS ppv FROM analytics.po_performance", {}, 6, 3),
        ("On-time delivery", "scalar",
         "SELECT round(100.0 * avg(on_time::int), 1) AS otd_pct FROM analytics.po_performance WHERE received_date IS NOT NULL", {}, 6, 3),
        ("Incoming lots rejected", "scalar",
         "SELECT count(*) FILTER (WHERE accepted = false) AS rejected FROM procurement.receipts", {}, 6, 3),
        ("Spend by category and month", "bar",
         "SELECT date_trunc('month', order_date)::date AS month, category, round(sum(spend_eur)) AS spend_eur "
         "FROM analytics.po_performance GROUP BY 1, 2 ORDER BY 1", bar(["month", "category"], "spend_eur", stacked=True), 12, 7),
        ("PPV by supplier (EUR)", "row",
         "SELECT supplier, round(sum(ppv_eur)) AS ppv_eur FROM analytics.po_performance GROUP BY 1 ORDER BY 2 DESC",
         bar("supplier", "ppv_eur"), 12, 7),
        ("Ibuprofen API unit price vs standard", "line",
         "SELECT order_date, supplier, unit_price_eur, standard_price_eur FROM analytics.po_performance "
         "WHERE material_id = 'M100' ORDER BY 1", bar(["order_date", "supplier"], "unit_price_eur"), 12, 7),
        ("Supplier scorecard", "table",
         "SELECT supplier, category, count(*) AS po_lines, round(sum(spend_eur)) AS spend_eur, "
         "round(sum(ppv_eur)) AS ppv_eur, round(100.0 * avg(on_time::int), 0) AS otd_pct, "
         "round(avg(greatest(days_late, 0)), 1) AS avg_days_late, "
         "count(*) FILTER (WHERE lot_accepted = false) AS lots_rejected "
         "FROM analytics.po_performance GROUP BY 1, 2 ORDER BY spend_eur DESC", {}, 12, 7),
    ]),
    ("2 · Manufacturing (MES)", [
        ("Batches produced", "scalar", "SELECT count(*) FROM mes.batches", {}, 6, 3),
        ("Average yield", "scalar", "SELECT round(100 * avg(yield), 1) AS yield_pct FROM analytics.batch_kpis", {}, 6, 3),
        ("Downtime (hours)", "scalar", "SELECT round(sum(minutes) / 60.0) FROM mes.downtime", {}, 6, 3),
        ("Batches rejected", "scalar", "SELECT count(*) FROM mes.batches WHERE disposition = 'Rejected'", {}, 6, 3),
        ("Batches per week by line", "bar",
         "SELECT date_trunc('week', start_ts)::date AS week, line, count(*) AS batches FROM mes.batches GROUP BY 1, 2 ORDER BY 1",
         bar(["week", "line"], "batches", stacked=True), 12, 7),
        ("Downtime by reason (hours)", "row",
         "SELECT reason, round(sum(minutes) / 60.0, 1) AS hours FROM mes.downtime GROUP BY 1 ORDER BY 2 DESC",
         bar("reason", "hours"), 12, 7),
        ("Line 1 downtime per month by reason", "bar",
         "SELECT date_trunc('month', start_ts)::date AS month, reason, round(sum(minutes) / 60.0, 1) AS hours "
         "FROM mes.downtime WHERE line = 'Line 1' GROUP BY 1, 2 ORDER BY 1",
         bar(["month", "reason"], "hours", stacked=True), 12, 7),
        ("Yield by product per month (%)", "line",
         "SELECT date_trunc('month', start_ts)::date AS month, product, round(100 * avg(yield), 2) AS yield_pct "
         "FROM analytics.batch_kpis GROUP BY 1, 2 ORDER BY 1", bar(["month", "product"], "yield_pct"), 12, 7),
    ]),
    ("3 · Quality control (LIMS)", [
        ("Samples tested", "scalar", "SELECT count(*) FROM lims.samples WHERE status = 'verified'", {}, 6, 3),
        ("Median release turnaround (h)", "scalar",
         "SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY tat_hours)::numeric, 1) FROM analytics.sample_tat WHERE kind = 'Release'", {}, 6, 3),
        ("Out-of-spec results", "scalar", "SELECT count(*) FROM lims.results WHERE out_of_spec", {}, 6, 3),
        ("Open backlog", "scalar", "SELECT count(*) FROM lims.samples WHERE status <> 'verified'", {}, 6, 3),
        ("Samples per week by kind", "bar",
         "SELECT date_trunc('week', date_sampled)::date AS week, kind, count(*) AS samples FROM lims.samples "
         "WHERE date_sampled >= '2026-05-01' GROUP BY 1, 2 ORDER BY 1", bar(["week", "kind"], "samples", stacked=True), 12, 7),
        ("Median turnaround by month (h)", "line",
         "SELECT date_trunc('month', date_received)::date AS month, kind, "
         "round(percentile_cont(0.5) WITHIN GROUP (ORDER BY tat_hours)::numeric, 1) AS median_tat_h "
         "FROM analytics.sample_tat WHERE tat_hours IS NOT NULL AND date_received >= '2026-05-01' GROUP BY 1, 2 ORDER BY 1",
         bar(["month", "kind"], "median_tat_h"), 12, 7),
        ("Out-of-spec rate by test (%)", "row",
         "SELECT test, round(100.0 * avg(out_of_spec::int), 2) AS oos_pct FROM lims.results GROUP BY 1 "
         "HAVING sum(out_of_spec::int) > 0 ORDER BY 2 DESC", bar("test", "oos_pct"), 12, 7),
        ("Release assay results (Ibuprofen tablets)", "scatter",
         "SELECT s.date_sampled, r.result AS assay_pct FROM lims.results r JOIN lims.samples s USING (sample_id) "
         "WHERE r.keyword = 'ASSAY' AND s.kind = 'Release' ORDER BY 1", bar("date_sampled", "assay_pct"), 12, 7),
    ]),
    ("4 · Supplier → batch → quality", [
        ("Release OOS rate by API supplier (%)", "bar",
         "SELECT api_supplier, round(100.0 * avg((disposition = 'Rejected')::int), 1) AS batch_reject_pct, "
         "count(*) AS batches FROM analytics.batch_kpis WHERE sku = 'SKU-2002' AND api_supplier IS NOT NULL "
         "AND disposition <> 'Pending QA' GROUP BY 1 ORDER BY 2 DESC", bar("api_supplier", "batch_reject_pct"), 12, 7),
        ("API supplier: price vs quality", "table",
         "SELECT b.api_supplier, count(*) AS batches, count(*) FILTER (WHERE disposition = 'Rejected') AS rejected, "
         "round(100.0 * avg((disposition = 'Rejected')::int), 1) AS reject_pct, "
         "(SELECT round(sum(ppv_eur)) FROM analytics.po_performance p WHERE p.supplier = b.api_supplier AND material_id = 'M100') AS api_ppv_eur "
         "FROM analytics.batch_kpis b WHERE sku = 'SKU-2002' AND api_supplier IS NOT NULL GROUP BY 1", {}, 12, 7),
        ("Monthly batch rejects by API supplier", "bar",
         "SELECT date_trunc('month', start_ts)::date AS month, api_supplier, count(*) FILTER (WHERE disposition = 'Rejected') AS rejected "
         "FROM analytics.batch_kpis WHERE sku = 'SKU-2002' AND api_supplier IS NOT NULL GROUP BY 1, 2 ORDER BY 1",
         bar(["month", "api_supplier"], "rejected", stacked=True), 12, 7),
        ("Rejected batches: which supplier lots went in", "table",
         "SELECT batch_id, product, supplier, material, supplier_lot, lot_accepted FROM analytics.lot_genealogy "
         "WHERE disposition = 'Rejected' AND material IN ('Ibuprofen API', 'Sodium chloride USP') ORDER BY batch_id", {}, 12, 7),
    ]),
]

existing = {d["name"]: d["id"] for d in api("GET", "/api/dashboard")}
for title, cards in DASHBOARDS:
    if title in existing:
        api("DELETE", f"/api/dashboard/{existing[title]}")
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
