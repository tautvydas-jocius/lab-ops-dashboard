"""Push the most recent generated LIMS samples into a live SENAITE 2.x through its JSON API.

Needs the master data from setup.py (client, sample types, points, specs, services).
Only products/materials that exist in SENAITE are pushed: tablets, granulate IPC, buffer and
sodium chloride incoming lots. Idempotent by ClientSampleID (= generator sample id).

SENAITE accepts a backdated DateSampled and DateReceived, but result capture and verification
are stamped with the time of this run, so turnaround read back from SENAITE reflects the push,
not the generated timeline.
Usage: SENAITE_PASSWORD=... python3 push.py [--days 14]
"""
import argparse
import csv
import os
from collections import defaultdict
from datetime import datetime, timedelta

from sapi import call, find

p = argparse.ArgumentParser()
p.add_argument("--days", type=int, default=14, help="push samples taken in the last N days of the dataset")
p.add_argument("--data", default=os.path.join(os.path.dirname(__file__), "..", "data"))
args = p.parse_args()

TYPE = {  # (generator sample_type) -> (SENAITE sample type, spec, sample point)
    "Ibuprofen 200 mg tablets": ("SKU-2002 Ibuprofen 200 mg tablets",
                                 "Release spec - SKU-2002 Ibuprofen 200 mg tablets", "Line 1 - tablet press discharge"),
    "Ibuprofen 200 mg tablets (in-process)": ("SKU-2002-G Ibuprofen granulate (in-process)",
                                              "IPC spec - SKU-2002-G granulate", "Line 1 - fluid-bed dryer outlet"),
    "Phosphate buffer pH 7.4": ("SKU-1001 Phosphate buffer pH 7.4, 500 mL",
                                "Release spec - SKU-1001 Phosphate buffer pH 7.4", "Line 2 - filling machine"),
    "Phosphate buffer pH 7.4 (in-process)": ("SKU-1001 Phosphate buffer pH 7.4, 500 mL",
                                             None, "Line 2 - filling machine"),
    "Sodium chloride USP (raw material)": ("SKU-3003 Sodium chloride USP (raw material)",
                                          "Acceptance spec - SKU-3003 Sodium chloride USP", "RM warehouse - sampling booth"),
}
KEYWORD = {"RM_ASSAY": "ASSAY", "RM_LOD": "LOD"}  # generator keyword -> SENAITE service keyword

rows = lambda name: list(csv.DictReader(open(os.path.join(args.data, name + ".csv"))))
samples = [s for s in rows("lims_samples") if s["sample_type"] in TYPE]
results = defaultdict(dict)
for r in rows("lims_results"):
    results[r["sample_id"]][KEYWORD.get(r["keyword"], r["keyword"])] = r["result"]
last = max(datetime.fromisoformat(s["date_sampled"]) for s in samples)
samples = [s for s in samples if datetime.fromisoformat(s["date_sampled"]) > last - timedelta(days=args.days)]

client = find("Client", "Production - Plant 1")
client_path = call("Client/" + client["uid"])["items"][0]["path"]
contact = find("Contact", "Paul Planner")["uid"]
uid = {}


def ref(pt, title):
    if title and (pt, title) not in uid:
        uid[pt, title] = find(pt, title)["uid"]
    return uid.get((pt, title))


def analyses_of(sample_uid):
    res = call("search?portal_type=Analysis&getAncestorsUIDs=%s&complete=yes&limit=50" % sample_uid)["items"]
    return {a["getKeyword"]: a for a in res}


existing = {s.get("getClientSampleID") for s in
            call("search?portal_type=AnalysisRequest&complete=yes&limit=2000")["items"]}
pushed = 0
for s in samples:
    if s["sample_id"] in existing:
        continue
    stype, spec, point = TYPE[s["sample_type"]]
    kws = list(results[s["sample_id"]]) or (["LOD"] if "granulate" in stype else ["FILLVOL"] if "in-process" in s["sample_type"] else
                                            ["ASSAY", "LOD"] if "Sodium" in stype else ["ASSAY"])
    data = {"portal_type": "AnalysisRequest", "parent_path": client_path, "Contact": contact,
            "SampleType": ref("SampleType", stype), "SamplePoint": ref("SamplePoint", point),
            "DateSampled": s["date_sampled"], "ClientSampleID": s["sample_id"],
            "ClientReference": s["source_ref"], "Analyses": kws}
    if spec:
        data["Specification"] = ref("AnalysisSpec", spec)
    sid = call("create", data)["items"][0]["uid"]
    call("update", {"uid": sid, "transition": "receive"})
    call("update", {"uid": sid, "DateReceived": s["date_received"]})
    if s["status"] == "verified":
        for kw, a in analyses_of(sid).items():
            if kw in results[s["sample_id"]]:
                call("update", {"uid": a["uid"], "Result": results[s["sample_id"]][kw]})
                call("update", {"uid": a["uid"], "transition": "submit"})
        for a in analyses_of(sid).values():
            if a["review_state"] == "to_be_verified":
                call("update", {"uid": a["uid"], "transition": "verify"})
    pushed += 1
    print(f"{s['sample_id']:10s} {s['source_ref']:22s} {stype}")
print(f"pushed {pushed} of {len(samples)} samples from the last {args.days} days")
