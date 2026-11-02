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
    ("1 · Sample throughput", [
        ("Samples confirmed", "scalar", "SELECT count(*) FROM lims.samples WHERE status = 'verified'", {}, 6, 3),
        ("Median release cycle time (h)", "scalar",
         "SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY cycle_hours)::numeric) FROM analytics.sample_cycle WHERE kind = 'Release'", {}, 6, 3),
        ("Median time to confirm (h)", "scalar",
         "SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY time_to_confirm_hours)::numeric, 1) FROM analytics.sample_cycle", {}, 6, 3),
        ("Open samples now", "scalar", "SELECT count(*) FROM lims.samples WHERE status <> 'verified'", {}, 6, 3),
        ("Samples received vs confirmed per week", "line",
         "SELECT week, sum(received) AS received, sum(confirmed) AS confirmed FROM ("
         "SELECT date_trunc('week', received_ts)::date AS week, 1 AS received, 0 AS confirmed FROM lims.samples "
         "UNION ALL SELECT date_trunc('week', verified_ts)::date, 0, 1 FROM lims.samples WHERE verified_ts IS NOT NULL) x "
         "GROUP BY 1 ORDER BY 1", bar("week", "received", "confirmed"), 12, 7),
        ("Median cycle time by month (h)", "bar",
         "SELECT date_trunc('month', received_ts)::date AS month, kind, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY cycle_hours)::numeric) AS median_h "
         "FROM analytics.sample_cycle WHERE cycle_hours IS NOT NULL GROUP BY 1, 2 ORDER BY 1", bar(["month", "kind"], "median_h"), 12, 7),
        ("Open analyses by state, end of each working day", "area",
         "SELECT day, state, open_analyses FROM lims.daily_wip ORDER BY 1",
         bar(["day", "state"], "open_analyses", stacked=True), 24, 8),
    ]),
    ("2 · Every sample: time to test and confirm", [
        ("Where release sample time goes, by month (median h)", "bar",
         "SELECT date_trunc('month', received_ts)::date AS month, "
         "round(percentile_cont(0.5) WITHIN GROUP (ORDER BY wait_for_analyst_hours)::numeric, 1) AS queued, "
         "round(percentile_cont(0.5) WITHIN GROUP (ORDER BY testing_hours)::numeric, 1) AS in_test, "
         "round(percentile_cont(0.5) WITHIN GROUP (ORDER BY wait_for_review_hours)::numeric, 1) AS waiting_for_review, "
         "round(percentile_cont(0.5) WITHIN GROUP (ORDER BY review_hours)::numeric, 1) AS review "
         "FROM analytics.sample_cycle WHERE kind = 'Release' AND verified_ts IS NOT NULL GROUP BY 1 ORDER BY 1",
         dict(bar("month", "queued", "in_test", "waiting_for_review", "review"), **{"stackable.stack_type": "stacked"}), 12, 7),
        ("Last 25 release samples: hours in each stage", "bar",
         "SELECT sample_id, round(wait_for_analyst_hours::numeric, 1) AS queued, round(testing_hours::numeric, 1) AS in_test, "
         "round(wait_for_review_hours::numeric, 1) AS waiting_for_review, round(review_hours::numeric, 1) AS review "
         "FROM analytics.sample_cycle WHERE kind = 'Release' AND verified_ts IS NOT NULL ORDER BY verified_ts DESC LIMIT 25",
         dict(bar("sample_id", "queued", "in_test", "waiting_for_review", "review"),
              **{"stackable.stack_type": "stacked", "graph.max_categories_enabled": False, "graph.x_axis.axis_enabled": "rotate-45"}), 12, 7),
        ("Time to confirm after last result (samples per bucket)", "bar",
         "SELECT CASE WHEN time_to_confirm_hours < 4 THEN '0-4 h' WHEN time_to_confirm_hours < 24 THEN '4-24 h' "
         "WHEN time_to_confirm_hours < 48 THEN '1-2 d' WHEN time_to_confirm_hours < 96 THEN '2-4 d' ELSE '4 d +' END AS bucket, "
         "count(*) AS samples, min(time_to_confirm_hours) AS sort_key FROM analytics.sample_cycle WHERE verified_ts IS NOT NULL "
         "GROUP BY 1 ORDER BY 3", bar("bucket", "samples"), 8, 7),
        ("Sample log: who tested, who confirmed, how long", "table",
         "SELECT sample_id, plan_id, received_ts::date AS received, analysts, runs, aborted_runs, bench_minutes, "
         "round(testing_hours::numeric, 1) AS testing_h, reviewer, review_minutes, "
         "round(time_to_confirm_hours::numeric, 1) AS confirm_h, round(cycle_hours::numeric, 1) AS total_h, "
         "CASE WHEN out_of_spec THEN 'OOS' ELSE '' END AS oos "
         "FROM analytics.sample_cycle WHERE verified_ts IS NOT NULL ORDER BY verified_ts DESC LIMIT 200", {}, 16, 7),
    ]),
    ("3 · Analysts", [
        ("Runs per analyst per month", "bar",
         "SELECT date_trunc('month', start_ts)::date AS month, analyst, count(*) AS runs FROM mes.executions GROUP BY 1, 2 ORDER BY 1",
         bar(["month", "analyst"], "runs"), 12, 7),
        ("Utilisation per analyst per week (% of available bench time)", "line",
         "SELECT date_trunc('week', day)::date AS week, person, round(100.0 * sum(booked_minutes) / NULLIF(sum(available_minutes), 0)) AS utilisation_pct "
         "FROM qc.person_days WHERE role = 'Analyst' GROUP BY 1, 2 HAVING sum(available_minutes) > 0 ORDER BY 1",
         bar(["week", "person"], "utilisation_pct"), 12, 7),
        ("Speed vs protocol standard per month (%; 100 = on standard)", "line",
         "SELECT date_trunc('month', start_ts)::date AS month, analyst, round(100.0 * sum(standard_minutes) / sum(actual_minutes)) AS efficiency_pct "
         "FROM analytics.analyst_runs GROUP BY 1, 2 ORDER BY 1", bar(["month", "analyst"], "efficiency_pct"), 12, 7),
        ("Analyst scorecard", "table",
         "SELECT analyst, lab_area, count(*) AS runs, round(sum(actual_minutes) / 60.0) AS bench_hours, "
         "round(100.0 * sum(standard_minutes) / sum(actual_minutes)) AS efficiency_pct, "
         "round(100.0 * avg((status = 'Completed')::int), 1) AS first_time_right_pct, "
         "count(*) FILTER (WHERE status = 'Aborted - analyst error') AS analyst_errors, "
         "round(percentile_cont(0.5) WITHIN GROUP (ORDER BY work_order_to_start_hours)::numeric, 1) AS median_wo_to_start_h "
         "FROM analytics.analyst_runs GROUP BY 1, 2 ORDER BY runs DESC", {}, 12, 7),
        ("Bench hours per analyst by test", "row",
         "SELECT analyst, keyword, round(sum(actual_minutes) / 60.0) AS hours FROM mes.executions GROUP BY 1, 2 ORDER BY 1",
         dict(bar(["analyst", "keyword"], "hours"), **{"stackable.stack_type": "stacked"}), 24, 6),
    ]),
    ("4 · QC reviewers: confirming samples", [
        ("Samples confirmed per reviewer per week", "bar",
         "SELECT date_trunc('week', verified_ts)::date AS week, reviewer, count(*) AS samples FROM lims.samples "
         "WHERE verified_ts IS NOT NULL GROUP BY 1, 2 ORDER BY 1", bar(["week", "reviewer"], "samples", stacked=True), 12, 7),
        ("Median time to confirm per week (h)", "line",
         "SELECT date_trunc('week', results_complete_ts)::date AS week, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY time_to_confirm_hours)::numeric, 1) AS median_h "
         "FROM analytics.sample_cycle WHERE verified_ts IS NOT NULL GROUP BY 1 ORDER BY 1", bar("week", "median_h"), 12, 7),
        ("Review minutes per sample: normal vs out-of-spec", "bar",
         "SELECT reviewer, CASE WHEN out_of_spec THEN 'OOS' ELSE 'In spec' END AS result, round(avg(review_minutes)) AS avg_minutes "
         "FROM lims.samples WHERE verified_ts IS NOT NULL GROUP BY 1, 2 ORDER BY 1", bar(["reviewer", "result"], "avg_minutes"), 12, 7),
        ("Reviewer scorecard", "table",
         "SELECT s.reviewer, count(*) AS samples, round(sum(review_minutes) / 60.0, 1) AS review_hours, round(avg(review_minutes), 1) AS avg_min_per_sample, "
         "round(percentile_cont(0.5) WITHIN GROUP (ORDER BY c.time_to_confirm_hours)::numeric, 1) AS median_confirm_h, "
         "count(*) FILTER (WHERE s.out_of_spec) AS oos_reviewed FROM lims.samples s JOIN analytics.sample_cycle c USING (sample_id) "
         "WHERE s.verified_ts IS NOT NULL GROUP BY 1 ORDER BY 2 DESC", {}, 12, 7),
    ]),
    ("5 · Where the lab stalls", [
        ("Analysis-days lost by cause per month", "bar",
         "SELECT date_trunc('month', day)::date AS month, reason, count(*) AS analysis_days FROM lims.wait_events "
         "WHERE day >= '2026-05-01' GROUP BY 1, 2 ORDER BY 1", bar(["month", "reason"], "analysis_days", stacked=True), 12, 7),
        ("Analyst capacity vs demand per week (hours)", "line",
         "SELECT d.week, d.available_h, r.demand_h FROM (SELECT date_trunc('week', day)::date AS week, round(sum(available_minutes) / 60.0) AS available_h "
         "FROM qc.person_days WHERE role = 'Analyst' GROUP BY 1) d JOIN (SELECT date_trunc('week', received_ts)::date AS week, "
         "round(sum(p.analyst_minutes) / 60.0) AS demand_h FROM lims.analyses a JOIN lims.samples s USING (sample_id) "
         "JOIN mes.protocols p USING (keyword) GROUP BY 1) r USING (week) ORDER BY 1", bar("week", "available_h", "demand_h"), 12, 7),
        ("Stock-outs: analysis-days waiting per material", "row",
         "SELECT m.name AS material, count(*) AS analysis_days FROM lims.wait_events w JOIN erp.materials m USING (material_id) "
         "WHERE reason = 'Waiting for stock' GROUP BY 1 ORDER BY 2 DESC", bar("material", "analysis_days"), 12, 7),
        ("Aborted runs by cause and analyst", "row",
         "SELECT status, analyst, count(*) AS runs FROM mes.executions WHERE status <> 'Completed' GROUP BY 1, 2 ORDER BY 3 DESC",
         dict(bar(["status", "analyst"], "runs"), **{"stackable.stack_type": "stacked"}), 12, 7),
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
