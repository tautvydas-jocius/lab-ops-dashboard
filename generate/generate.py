"""Synthetic but coherent pharma plant data: procurement -> MES -> LIMS.

One seeded run produces CSVs in ../data/ that share keys across systems:
  purchase order line -> receipt (supplier lot) -> incoming LIMS sample
  receipt lots consumed by MES batches -> in-process + release LIMS samples

Stories baked in so the dashboards have something to find:
  - Supplier "Hubei Pharma Chem" raises its ibuprofen API price from August (PPV turns red)
  - Its lots carry slightly lower assay, so tablet batches made from them fail assay more often
  - Line 1 tablet press has recurring tooling downtime in September
Stdlib only. Usage: python3 generate.py [--days 184] [--seed 42]
"""
import argparse
import csv
import os
import random
from datetime import date, datetime, timedelta

p = argparse.ArgumentParser()
p.add_argument("--start", default="2026-05-01")
p.add_argument("--days", type=int, default=184)
p.add_argument("--seed", type=int, default=42)
p.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data"))
args = p.parse_args()
rnd = random.Random(args.seed)
START = date.fromisoformat(args.start)
END = START + timedelta(days=args.days)
os.makedirs(args.out, exist_ok=True)

# --- master data ---------------------------------------------------------------
SUPPLIERS = [  # id, name, country, category
    ("S01", "Hubei Pharma Chem", "CN", "API"),
    ("S02", "IOL Chemicals", "IN", "API"),
    ("S03", "JRS Pharma", "DE", "Excipients"),
    ("S04", "Meggle Excipients", "DE", "Excipients"),
    ("S05", "K+S Minerals", "DE", "Raw materials"),
    ("S06", "Merck Life Science", "DE", "Raw materials"),
    ("S07", "Gerresheimer", "DE", "Primary packaging"),
    ("S08", "Constantia Flexibles", "AT", "Primary packaging"),
    ("S09", "Smurfit Westrock", "LT", "Secondary packaging"),
    ("S10", "VWR International", "BE", "Lab consumables"),
    ("S11", "Agilent Technologies", "US", "Lab consumables"),
    ("S12", "Fette Compacting", "DE", "Maintenance & spares"),
]
# id, name, spend type, category, uom, standard price EUR, suppliers, typical order qty
MATERIALS = [
    ("M100", "Ibuprofen API", "Direct", "API", "kg", 18.50, ["S01", "S02"], 2000),
    ("M110", "Microcrystalline cellulose", "Direct", "Excipients", "kg", 4.20, ["S03"], 1500),
    ("M111", "Lactose monohydrate", "Direct", "Excipients", "kg", 2.90, ["S04"], 1500),
    ("M112", "Croscarmellose sodium", "Direct", "Excipients", "kg", 11.00, ["S03"], 200),
    ("M113", "Magnesium stearate", "Direct", "Excipients", "kg", 7.80, ["S04"], 100),
    ("M200", "Sodium chloride USP", "Direct", "Raw materials", "kg", 1.10, ["S05"], 3000),
    ("M201", "Disodium phosphate", "Direct", "Raw materials", "kg", 6.40, ["S06"], 400),
    ("M202", "Potassium dihydrogen phosphate", "Direct", "Raw materials", "kg", 7.10, ["S06"], 300),
    ("M300", "500 mL HDPE bottle", "Direct", "Primary packaging", "pcs", 0.21, ["S07"], 60000),
    ("M301", "Alu/PVC blister foil", "Direct", "Primary packaging", "m2", 0.95, ["S08"], 20000),
    ("M302", "Folding carton", "Direct", "Secondary packaging", "pcs", 0.06, ["S09"], 100000),
    ("M400", "HPLC column C18", "Indirect", "Lab consumables", "pcs", 640.0, ["S11"], 4),
    ("M401", "Lab glassware & filters", "Indirect", "Lab consumables", "lot", 380.0, ["S10"], 3),
    ("M402", "Tablet press punches set", "Indirect", "Maintenance & spares", "set", 4200.0, ["S12"], 1),
]
MAT = {m[0]: m for m in MATERIALS}
BUYERS = ["A. Petraitis", "R. Kazlauskaite", "J. Novak"]

# SKU -> line, batch size, bill of materials (material, kg or pcs per batch), tests
TESTS = {  # keyword: (title, unit, min, max) ; None = no limit on that side
    "APPEAR": ("Appearance", "", 1, 1), "ID_IR": ("Identity (IR)", "", 1, 1),
    "ASSAY": ("Assay", "%", 95.0, 105.0), "IMPTOT": ("Total impurities", "%", None, 0.5),
    "DISS": ("Dissolution 30 min", "%", 80, None), "WATER": ("Water (KF)", "%", None, 1.5),
    "HARD": ("Hardness", "N", 60, 120), "AVGWT": ("Average weight", "mg", 285, 315),
    "TAMC": ("TAMC", "cfu/g", None, 1000), "ECOLI": ("E. coli", "cfu/g", 0, 0),
    "LOD": ("Loss on drying", "%", None, 2.0), "PH": ("pH", "", 7.2, 7.6),
    "OSMO": ("Osmolality", "mOsm/kg", 280, 310), "FILLVOL": ("Fill volume", "mL", 495, 510),
    "RM_ASSAY": ("Assay (raw material)", "%", 98.5, 101.5), "RM_LOD": ("Loss on drying (RM)", "%", None, 0.5),
}
SKUS = {
    "SKU-2002": dict(name="Ibuprofen 200 mg tablets", line="Line 1", size=300000, uom="tablets",
                     bom=[("M100", 60), ("M110", 18), ("M111", 9), ("M112", 2.4), ("M113", 0.6),
                          ("M301", 2600), ("M302", 15000)],
                     release=["APPEAR", "ID_IR", "ASSAY", "IMPTOT", "DISS", "WATER", "HARD", "AVGWT", "TAMC", "ECOLI"],
                     ipc=("Line 1 - fluid-bed dryer outlet", ["LOD"], 3), per_week=4,
                     sample_type="Ibuprofen 200 mg tablets", point="Line 1 - tablet press discharge"),
    "SKU-1001": dict(name="Phosphate buffer pH 7.4, 500 mL", line="Line 2", size=8000, uom="bottles",
                     bom=[("M200", 36), ("M201", 9.6), ("M202", 1.1), ("M300", 8100)],
                     release=["APPEAR", "PH", "OSMO", "FILLVOL", "TAMC", "ECOLI"],
                     ipc=("Line 2 - filling machine", ["FILLVOL"], 2), per_week=3,
                     sample_type="Phosphate buffer pH 7.4", point="Line 2 - filling machine"),
}
RM_TESTED = {"M100", "M110", "M111", "M200", "M201", "M202"}  # incoming inspection in LIMS


def ts(d, h0=6, h1=18):
    return datetime(d.year, d.month, d.day, rnd.randint(h0, h1 - 1), rnd.randint(0, 59))


def workday(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def write(name, header, rows):
    with open(os.path.join(args.out, name + ".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows([[c.strftime("%Y-%m-%d %H:%M") if isinstance(c, datetime) else c for c in r] for r in rows])
    print(f"{name:18s} {len(rows):6d} rows")


# --- procurement: POs + receipts -------------------------------------------------
po_lines, receipts = [], []
lots = {m: [] for m in MAT}  # material -> list of receipt dicts (inventory)
po_no = 4500010000


def unit_price(mid, sid, d):
    std = MAT[mid][5]
    drift = rnd.gauss(0, 0.025)
    if sid == "S01" and d >= date(2026, 8, 1):
        drift += 0.11  # the August price increase
    if sid == "S02":
        drift += 0.04  # dearer but cleaner alternative source
    return round(std * (1 + drift), 4 if std < 1 else 2)


d = START - timedelta(days=75)  # stock built before the window so early batches have lots
while d < END:
    for mid, name, stype, cat, uom, std, sups, qty in MATERIALS:
        weekly = 0.55 if stype == "Direct" else 0.12
        if rnd.random() > weekly:
            continue
        sid = rnd.choice(sups) if mid != "M100" else ("S01" if rnd.random() < 0.65 else "S02")
        po_no += 1
        order_d = workday(d + timedelta(days=rnd.randint(0, 4)))
        lead = {"CN": 35, "IN": 30, "US": 21}.get(SUPPLIERS[int(sid[1:]) - 1][2], 12)
        promised = order_d + timedelta(days=lead)
        late = rnd.random() < (0.30 if sid in ("S01", "S08") else 0.08)
        received = workday(promised + timedelta(days=rnd.randint(2, 12) if late else rnd.randint(-3, 0)))
        q = round(qty * rnd.uniform(0.8, 1.3), 0 if uom in ("pcs", "set", "lot") else 1)
        price = unit_price(mid, sid, order_d)
        po_lines.append([po_no, 10, sid, mid, stype, cat, order_d, promised, q, uom, price, std,
                         round((price - std) * q, 2), rnd.choice(BUYERS)])
        if received < END:
            q_rec = q if rnd.random() > 0.07 else round(q * rnd.uniform(0.85, 0.98), 1)
            rec = dict(receipt_id=f"GR{len(receipts) + 1:05d}", po=po_no, sid=sid, mid=mid,
                       date=received, qty=q_rec, lot=f"{sid}-{received:%y%m}-{rnd.randint(100, 999)}")
            receipts.append(rec)
            lots[mid].append(rec)
    d += timedelta(days=7)

write("po_lines", ["po_number", "po_line", "supplier_id", "material_id", "spend_type", "category",
                   "order_date", "promised_date", "quantity", "uom", "unit_price_eur",
                   "standard_price_eur", "ppv_eur", "buyer"], po_lines)
write("suppliers", ["supplier_id", "name", "country", "category"], SUPPLIERS)
write("materials", ["material_id", "name", "spend_type", "category", "uom", "standard_price_eur"],
      [m[:6] for m in MATERIALS])

# --- LIMS helpers ------------------------------------------------------------------
samples, results = [], []


def value(kw, bias=0.0):
    """Mostly in spec, occasionally out; bias shifts assay-type results."""
    t = TESTS[kw]
    if t[2] == 1 and t[3] == 1:
        return 1 if rnd.random() > 0.004 else 0
    if kw == "ECOLI":
        return 0
    lo, hi = t[2], t[3]
    centre = {"ASSAY": 99.8, "IMPTOT": 0.2, "DISS": 91, "WATER": 0.9, "HARD": 88, "AVGWT": 300,
              "TAMC": 60, "LOD": 1.2, "PH": 7.4, "OSMO": 295, "FILLVOL": 503,
              "RM_ASSAY": 99.9, "RM_LOD": 0.2}[kw] + bias
    spread = {"ASSAY": 1.6, "IMPTOT": 0.09, "DISS": 4, "WATER": 0.2, "HARD": 10, "AVGWT": 5,
              "TAMC": 70, "LOD": 0.33, "PH": 0.06, "OSMO": 5, "FILLVOL": 2.6,
              "RM_ASSAY": 0.55, "RM_LOD": 0.1}[kw]
    v = max(0.0, rnd.gauss(centre, spread))
    return round(v, 0 if kw in ("TAMC", "DISS", "HARD", "OSMO") else 2)


def oos(kw, v):
    _, _, lo, hi = TESTS[kw]
    return (lo is not None and v < lo) or (hi is not None and v > hi)


def add_sample(sid, source, ref, sku_or_mat, stype, point, sampled, kws, bias=0.0, kind="Release"):
    received = sampled + timedelta(minutes=rnd.randint(20, 240))
    hours = rnd.gauss(46 if kind == "Release" else 5, 14 if kind == "Release" else 2)
    if kind == "Incoming":
        hours = rnd.gauss(30, 10)
    done = received + timedelta(hours=max(1.5, hours))
    if done > datetime.combine(END, datetime.min.time()):
        status, done_s, ver = "sample_received", "", ""
    else:
        status = "verified"
        ver = done + timedelta(hours=max(0.5, rnd.gauss(6, 4)))
        done_s = ver
    any_oos = False
    for kw in kws:
        v = value(kw, bias if kw in ("ASSAY", "RM_ASSAY") else 0.0)
        o = oos(kw, v)
        any_oos |= o
        if status == "verified":
            t, unit, lo, hi = TESTS[kw]
            results.append([sid, kw, t, v, unit, lo, hi, o, done - timedelta(minutes=rnd.randint(0, 600))])
    samples.append([sid, kind, source, ref, sku_or_mat, stype, point, sampled, received, done_s, status,
                    any_oos if status == "verified" else ""])


s_no = 0
for r in receipts:
    if r["mid"] in RM_TESTED:
        s_no += 1
        bias = -1.0 if r["sid"] == "S01" and r["date"] >= date(2026, 7, 15) else 0.0
        kws = ["APPEAR", "ID_IR", "RM_ASSAY", "RM_LOD"]
        add_sample(f"RM-{s_no:05d}", "Procurement", r["lot"], r["mid"], MAT[r["mid"]][1] + " (raw material)",
                   "RM warehouse - sampling booth", ts(r["date"]), kws, bias, kind="Incoming")
        r["lims_sample"] = f"RM-{s_no:05d}"
        r["accepted"] = not samples[-1][11] if samples[-1][11] != "" else ""

write("receipts", ["receipt_id", "po_number", "supplier_id", "material_id", "received_date",
                   "quantity", "supplier_lot", "lims_sample_id", "accepted"],
      [[r["receipt_id"], r["po"], r["sid"], r["mid"], r["date"], r["qty"], r["lot"],
        r.get("lims_sample", ""), r.get("accepted", "")] for r in receipts])

# --- MES: batches, consumption, downtime --------------------------------------------
batches, consumption, downtime = [], [], []
DOWN = ["Changeover", "Tooling (punches)", "Material shortage", "Cleaning", "Electrical fault", "Awaiting QA"]
b_seq = {k: 0 for k in SKUS}
d = START
while d < END:
    for sku, s in SKUS.items():
        for _ in range(s["per_week"]):
            day = workday(d + timedelta(days=rnd.randint(0, 4)))
            if day >= END:
                continue
            b_seq[sku] += 1
            bid = f"{'B' if sku == 'SKU-2002' else 'PB'}{day:%y%m}-{b_seq[sku]:03d}"
            start = ts(day, 6, 10)
            # consume the oldest accepted lot received before the batch started
            api_sup, used = None, []
            for mid, per in s["bom"]:
                ok = [l for l in lots[mid] if l["date"] <= day and l.get("accepted", True) is not False]
                if not ok:
                    continue
                lot = ok[-1] if rnd.random() < 0.7 else rnd.choice(ok[-3:])
                used.append([bid, mid, lot["lot"], lot["receipt_id"], round(per * rnd.uniform(0.98, 1.03), 2)])
                if mid == "M100":
                    api_sup = lot["sid"]
            consumption += used
            run_h = rnd.gauss(14 if sku == "SKU-2002" else 9, 1.5)
            dt_rows = []
            for _ in range(rnd.choice([0, 1, 1, 2, 3])):
                reason = rnd.choice(DOWN)
                if s["line"] == "Line 1" and date(2026, 9, 1) <= day < date(2026, 10, 1) and rnd.random() < 0.6:
                    reason = "Tooling (punches)"
                mins = int(rnd.expovariate(1 / (95 if reason.startswith("Tooling") else 40))) + 10
                dt_rows.append([bid, s["line"], start + timedelta(hours=rnd.uniform(1, run_h)), mins, reason])
            downtime += dt_rows
            end = start + timedelta(hours=run_h, minutes=sum(r[3] for r in dt_rows))
            yld = min(0.995, rnd.gauss(0.965, 0.015))
            good = int(s["size"] * yld)
            # release sample from the finished batch, IPC samples during the run
            bias = -3.2 if api_sup == "S01" and day >= date(2026, 7, 20) else 0.0
            ipc_point, ipc_tests, n_ipc = s["ipc"]
            for i in range(n_ipc):
                s_no += 1
                add_sample(f"IPC-{s_no:05d}", "MES", bid, sku, s["sample_type"] + " (in-process)", ipc_point,
                           start + timedelta(hours=run_h * (i + 1) / (n_ipc + 1)), ipc_tests, kind="In-process")
            s_no += 1
            add_sample(f"REL-{s_no:05d}", "MES", bid, sku, s["sample_type"], s["point"],
                       end + timedelta(minutes=30), s["release"], bias, kind="Release")
            rel = samples[-1]
            disposition = ("Pending QA" if rel[10] != "verified" else "Rejected" if rel[11] else "Released")
            batches.append([bid, sku, s["name"], s["line"], start, end, round(run_h, 2), s["size"], good,
                            s["size"] - good, s["uom"], api_sup or "", disposition])
    d += timedelta(days=7)

write("mes_batches", ["batch_id", "sku", "product", "line", "start_ts", "end_ts", "planned_run_hours",
                      "planned_qty", "good_qty", "scrap_qty", "uom", "api_supplier_id", "disposition"], batches)
write("mes_consumption", ["batch_id", "material_id", "supplier_lot", "receipt_id", "quantity"], consumption)
write("mes_downtime", ["batch_id", "line", "start_ts", "minutes", "reason"], downtime)
write("lims_samples", ["sample_id", "kind", "source_system", "source_ref", "product_or_material", "sample_type",
                       "sample_point", "date_sampled", "date_received", "date_verified", "status", "out_of_spec"],
      samples)
write("lims_results", ["sample_id", "keyword", "test", "result", "unit", "spec_min", "spec_max",
                       "out_of_spec", "captured_ts"], results)
