"""Extract samples and results from a live SENAITE into the warehouse CSV shape.

Writes ../data/senaite/lims_samples.csv and lims_results.csv with the same columns the
generator produces, so warehouse/load.sql can load either source.
Usage: SENAITE_PASSWORD=... python3 extract.py
"""
import csv
import os

from sapi import call

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "senaite")
os.makedirs(OUT, exist_ok=True)
ts = lambda v: (v or "")[:16].replace("T", " ")


def search(portal_type):
    items, start = [], 0
    while True:
        page = call(f"search?portal_type={portal_type}&complete=yes&limit=200&b_start={start}")
        items += page["items"]
        if not page.get("next"):
            return items
        start += 200


samples = search("AnalysisRequest")
analyses = search("Analysis")
by_sample = {}
for a in analyses:
    by_sample.setdefault(a["parent_uid"] if "parent_uid" in a else a["getRequestUID"], []).append(a)

s_rows, r_rows = [], []
for s in samples:
    sid = s.get("getClientSampleID") or s["id"]
    stype = (s.get("getSampleTypeTitle") or "")
    plan = "SP-IN" if "raw material" in stype else "SP-IPC" if "in-process" in stype or sid.startswith("IPC") else "SP-REL"
    res = by_sample.get(s["uid"], [])
    s_rows.append([sid, plan, "SENAITE", s.get("getClientReference") or "", "", stype,
                   s.get("getSamplePointTitle") or "", ts(s.get("getDateSampled")), ts(s.get("getDateReceived")), "", "",
                   ts(s.get("getDateVerified")), "", "", s["review_state"], "", "", ""])
    for a in res:
        rr = a.get("ResultsRange") or {}
        try:
            v = float(a.get("Result"))
        except (TypeError, ValueError):
            continue
        lo = float(rr["min"]) if rr.get("min") not in (None, "") else None
        hi = float(rr["max"]) if rr.get("max") not in (None, "") else None
        o = (lo is not None and v < lo) or (hi is not None and v > hi)
        r_rows.append([a["uid"], sid, a["getKeyword"], a.get("title"), a.get("Unit") or "", lo, hi, v, o,
                       a["review_state"], ts(a.get("ResultCaptureDate")), ""])
    flags = [r[8] for r in r_rows if r[1] == sid]
    s_rows[-1][15] = any(flags) if flags and s["review_state"] == "verified" else ""

for name, header, rows in [
    ("lims_samples", ["sample_id", "plan_id", "trigger", "trigger_ref", "material_id", "sample_type", "sample_point",
                      "logged_ts", "received_ts", "results_complete_ts", "review_start_ts", "verified_ts", "reviewer",
                      "review_minutes", "status", "out_of_spec", "queued_hours", "in_test_hours"], s_rows),
    ("lims_analyses", ["analysis_id", "sample_id", "keyword", "test", "unit", "spec_min", "spec_max", "result",
                       "out_of_spec", "status", "completed_ts", "execution_id"], r_rows)]:
    with open(os.path.join(OUT, name + ".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"{name:14s} {len(rows):5d} rows -> {OUT}")
