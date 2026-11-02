"""Synthetic QC lab in a pharma plant: ERP -> LIMS (SENAITE) -> MES -> ERP inventory, simulated day by day.

  ERP planning: process orders fire predefined sampling plans.
  LIMS (SENAITE): QC logs the samples with predefined analyses and specifications, then pushes
    each analysis to MES as a work order.
  MES: executes the test protocol (analyst, instrument, steps), consumes lab stock lots from ERP
    inventory (FEFO) and returns the result to LIMS, where QC verifies the sample.
  ERP procurement: keeps lab stock topped up by reorder point (POs, receipts, stock lots). QC never
    talks to procurement; it only sees stock as available or not.

Turnaround and backlog are not drawn from a distribution: they come out of a FIFO queue worked
by a fixed number of analyst-minutes per day, so demand spikes and stock-outs show up as delays.

Stories baked in:
  - Acetonitrile (HPLC solvent) price rises ~35% from August: PPV on lab stock.
  - One TSA plate lot fails growth promotion in September: TAMC tests aborted and repeated, the
    lot is blocked in ERP inventory and plates run short until procurement's next delivery.
  - The KF reagent supplier delivers late a quarter of the time: water tests wait for stock.
  - September volume +50% on tablets: chemistry backlog and turnaround climb.
Stdlib only. Usage: python3 generate.py [--seed 42]
"""
import argparse
import csv
import os
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta

p = argparse.ArgumentParser()
p.add_argument("--start", default="2026-05-01")
p.add_argument("--days", type=int, default=184)
p.add_argument("--seed", type=int, default=42)
p.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data"))
args = p.parse_args()
rnd = random.Random(args.seed)
START = date.fromisoformat(args.start)
END = START + timedelta(days=args.days)
WARMUP = START - timedelta(days=70)  # procurement runs earlier so stock exists on day one
os.makedirs(args.out, exist_ok=True)
at = lambda d, h, m=0: datetime.combine(d, time(h, m))

# --- ERP master data ---------------------------------------------------------------------
SUPPLIERS = [  # id, name, country, category, lead days, late probability
    ("S06", "Merck Life Science", "DE", "Lab chemicals", 8, 0.25),
    ("S10", "VWR International", "BE", "Lab chemicals", 6, 0.08), ("S11", "Agilent Technologies", "US", "Lab consumables", 14, 0.08),
    ("S13", "EDQM", "FR", "Reference standards", 21, 0.05), ("S14", "bioMérieux", "FR", "Microbiology media", 7, 0.08),
]
SUP = {s[0]: s for s in SUPPLIERS}
# id: name, type, uom, std price EUR, suppliers, order qty, reorder point (lab stock), shelf life days
MAT = {
    "L01": ("Acetonitrile HPLC grade", "Lab stock", "L", 28.0, ["S06", "S10"], 40, 18, 730),
    "L02": ("Ibuprofen CRS", "Lab stock", "mg", 3.20, ["S13"], 1500, 650, 365),
    "L03": ("Ibuprofen impurity mix CRS", "Lab stock", "mg", 9.0, ["S13"], 120, 45, 365),
    "L04": ("HPLC vials 2 mL", "Lab stock", "pcs", 0.35, ["S11"], 3000, 900, 1825),
    "L05": ("Karl Fischer reagent", "Lab stock", "L", 95.0, ["S06"], 4, 1.2, 365),
    "L06": ("pH buffer set", "Lab stock", "L", 40.0, ["S10"], 3, 0.8, 365),
    "L07": ("TSA plates", "Lab stock", "pcs", 1.10, ["S14"], 400, 160, 90),
    "L08": ("MacConkey broth", "Lab stock", "L", 60.0, ["S14"], 4, 1.2, 180),
    "L09": ("Potassium phosphate (reagent)", "Lab stock", "kg", 45.0, ["S10"], 3, 1.0, 1095),
    "L10": ("Osmolality standard", "Lab stock", "pcs", 6.0, ["S10"], 60, 20, 365),
    "P2002": ("Ibuprofen 200 mg tablets", "Product", "tablets", None, [], None, None, None),
    "P1001": ("Phosphate buffer pH 7.4, 500 mL", "Product", "bottles", None, [], None, None, None),
}
BUYERS = ["A. Petraitis", "R. Kazlauskaite", "J. Novak"]

# --- LIMS: analyses and specifications ----------------------------------------------------
TESTS = {  # keyword: (title, unit, min, max)
    "APPEAR": ("Appearance", "", 1, 1), "ID_IR": ("Identity (IR)", "", 1, 1),
    "ASSAY": ("Assay (HPLC)", "%", 95.0, 105.0), "IMPTOT": ("Total impurities (HPLC)", "%", None, 0.5),
    "DISS": ("Dissolution 30 min", "%", 80, None), "WATER": ("Water (Karl Fischer)", "%", None, 1.5),
    "HARD": ("Hardness", "N", 60, 120), "AVGWT": ("Average weight", "mg", 285, 315),
    "TAMC": ("TAMC", "cfu/g", None, 1000), "ECOLI": ("E. coli", "cfu/g", 0, 0),
    "LOD": ("Loss on drying", "%", None, 2.0), "PH": ("pH", "", 7.2, 7.6),
    "OSMO": ("Osmolality", "mOsm/kg", 280, 310), "FILLVOL": ("Fill volume", "mL", 495, 510),
}
# --- MES: test protocols with analyst minutes, elapsed minutes, instrument, stock consumed per run
PROTOCOLS = {
    "APPEAR": ("TP-001", 5, 5, "Visual bench", "chem", []),
    "ID_IR": ("TP-002", 20, 25, "FTIR-01", "chem", []),
    "ASSAY": ("TP-010", 90, 240, "HPLC", "chem", [("L01", 0.40), ("L02", 25), ("L04", 6)]),
    "IMPTOT": ("TP-011", 110, 300, "HPLC", "chem", [("L01", 0.60), ("L03", 5), ("L04", 8)]),
    "DISS": ("TP-020", 140, 200, "DISS-01", "chem", [("L09", 0.05), ("L04", 6)]),
    "WATER": ("TP-030", 30, 40, "KF-01", "chem", [("L05", 0.06)]),
    "LOD": ("TP-031", 25, 120, "Balance + oven", "chem", []),
    "HARD": ("TP-040", 20, 25, "Hardness tester", "chem", []),
    "AVGWT": ("TP-041", 20, 25, "Balance", "chem", []),
    "PH": ("TP-050", 15, 20, "pH meter", "chem", [("L06", 0.03)]),
    "OSMO": ("TP-051", 20, 25, "Osmometer", "chem", [("L10", 1)]),
    "FILLVOL": ("TP-052", 15, 15, "Balance", "chem", []),
    "TAMC": ("TP-060", 30, 4320, "Incubator 30-35 C", "micro", [("L07", 4)]),
    "ECOLI": ("TP-061", 30, 4320, "Incubator 30-35 C", "micro", [("L08", 0.1), ("L07", 2)]),
}
# QC people. speed = actual / standard bench minutes; error = chance a run is aborted by analyst error.
# Absences and the August new hire are what make throughput move.
PEOPLE = {
    "R. Petrauskas": dict(role="Analyst", area="chem", speed=0.90, error=0.008, start=None, off=[(date(2026, 8, 3), date(2026, 8, 14))]),
    "L. Vaitkute": dict(role="Analyst", area="chem", speed=1.00, error=0.012, start=None, off=[(date(2026, 7, 13), date(2026, 7, 31))]),
    "M. Stankus": dict(role="Analyst", area="chem", speed=1.35, error=0.05, start=date(2026, 8, 17), off=[]),
    "E. Grigas": dict(role="Analyst", area="micro", speed=1.00, error=0.0, start=None, off=[(date(2026, 6, 29), date(2026, 7, 3))]),
    "K. Mockus": dict(role="Reviewer", start=None, off=[(date(2026, 7, 20), date(2026, 7, 31))]),
    "D. Zukaite": dict(role="Reviewer", start=None, off=[(date(2026, 8, 10), date(2026, 8, 21))]),
}
ANALYSTS = {"chem": [n for n, p in PEOPLE.items() if p.get("area") == "chem"],
            "micro": [n for n, p in PEOPLE.items() if p.get("area") == "micro"]}
REVIEWERS = [n for n, p in PEOPLE.items() if p["role"] == "Reviewer"]
MINUTES_PER_DAY = {"chem": 400, "micro": 300, "review": 120}  # productive minutes per person per day


def present(name, d):
    p = PEOPLE[name]
    return d.weekday() < 5 and (p["start"] is None or d >= p["start"]) and not any(a <= d <= b for a, b in p["off"])


def speed(name, d):
    """New hires start slow and converge on their long-run pace over ~10 weeks."""
    p = PEOPLE[name]
    if p["start"] is None:
        return p["speed"]
    weeks = (d - p["start"]).days / 7
    return 1.05 + (p["speed"] - 1.05) * max(0.0, 1 - weeks / 10)

RELEASE_2002 = ["APPEAR", "ID_IR", "ASSAY", "IMPTOT", "DISS", "WATER", "HARD", "AVGWT", "TAMC", "ECOLI"]
RELEASE_1001 = ["APPEAR", "PH", "OSMO", "FILLVOL", "TAMC", "ECOLI"]
# ERP sampling plans: id, trigger, material, sample type, sample point, samples per trigger, analyses
PLANS = [
    ("SP-IPC-2002", "Process order", "P2002", "Ibuprofen 200 mg tablets (in-process)", "Line 1 - fluid-bed dryer outlet", 3, ["LOD"]),
    ("SP-REL-2002", "Process order", "P2002", "Ibuprofen 200 mg tablets", "Line 1 - tablet press discharge", 1, RELEASE_2002),
    ("SP-IPC-1001", "Process order", "P1001", "Phosphate buffer pH 7.4 (in-process)", "Line 2 - filling machine", 2, ["FILLVOL"]),
    ("SP-REL-1001", "Process order", "P1001", "Phosphate buffer pH 7.4", "Line 2 - filling machine", 1, RELEASE_1001),
]
PLANS_BY_MAT = defaultdict(list)
for pl in PLANS:
    PLANS_BY_MAT[pl[2]].append(pl)

# --- state ----------------------------------------------------------------------------------
pos, receipts, batches, movements, orders = [], [], {}, [], []
samples, analyses, executions, consumption = {}, {}, [], []
open_po = defaultdict(float)  # material -> qty on order
due = defaultdict(list)       # date -> receipts arriving
queue = []                    # analysis ids waiting for an analyst
po_no, gr_no, mv_no, s_no, a_no, e_no = 4500010000, 0, 0, 0, 0, 0
BAD_TSA = None                # the TSA lot that fails growth promotion
gp_failures = defaultdict(int)
waits, daily_wip, person_days, review_queue = [], [], [], []
runs_by_sample = defaultdict(list)  # sample -> [(start, end)] of every MES run, for in-test vs queued time


def workday(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def price(mid, sid, d):
    std = MAT[mid][3]
    drift = rnd.gauss(0, 0.025)
    if mid == "L01" and d >= date(2026, 8, 1):
        drift += 0.35  # acetonitrile shortage
    return round(std * (1 + drift), 2 if std >= 1 else 3)


def raise_po(mid, d, sid=None):
    global po_no
    name, mtype, uom, std, sups, qty, rop, shelf = MAT[mid]
    sid = sid or rnd.choice(sups)
    _, sname, country, _, lead, late_p = SUP[sid]
    po_no += 1
    q = round(qty * rnd.uniform(0.9, 1.2), 0 if uom in ("pcs", "mg", "kg") else 1)
    promised = workday(d + timedelta(days=lead))
    late = rnd.random() < late_p
    arrive = workday(promised + timedelta(days=rnd.randint(2, 10)) if late else promised - timedelta(days=rnd.randint(0, 2)))
    up = price(mid, sid, d)
    pos.append([po_no, 10, sid, mid, mtype, d, promised, q, uom, up, std, round((up - std) * q, 2), rnd.choice(BUYERS)])
    open_po[mid] += q
    due[arrive].append((po_no, sid, mid, q))


def move(batch_id, mid, kind, qty, ts, ref):
    global mv_no
    mv_no += 1
    movements.append([f"MV{mv_no:06d}", batch_id, mid, kind, round(qty, 4), ts, ref])


def log_sample(plan, trigger_ref, logged, received):
    global s_no, a_no
    plan_id, trigger, mid, stype, point, _, kws = plan
    s_no += 1
    prefix = "IPC" if "IPC" in plan_id else "REL"
    sid = f"{prefix}-{s_no:05d}"
    samples[sid] = dict(sample_id=sid, plan_id=plan_id, trigger=trigger, trigger_ref=trigger_ref, material_id=mid,
                        sample_type=stype, sample_point=point, logged_ts=logged, received_ts=received,
                        completed_ts=None, review_start_ts=None, verified_ts=None, reviewer=None, review_minutes=None,
                        status="received", out_of_spec=None, analyses=[])
    for kw in kws:
        a_no += 1
        aid = f"A{a_no:06d}"
        t, unit, lo, hi = TESTS[kw]
        analyses[aid] = dict(analysis_id=aid, sample_id=sid, keyword=kw, test=t, unit=unit, spec_min=lo, spec_max=hi,
                             result=None, out_of_spec=None, status="unassigned", completed_ts=None, attempts=0)
        samples[sid]["analyses"].append(aid)
        queue.append(aid)
    return sid


def value(kw, sample):
    t = TESTS[kw]
    if t[2] == 1 and t[3] == 1:
        return 1 if rnd.random() > 0.003 else 0
    if kw == "ECOLI":
        return 0
    bias = 0.0
    centre, spread = {"ASSAY": (99.8, 1.6), "IMPTOT": (0.2, 0.09), "DISS": (91, 4), "WATER": (0.9, 0.2),
                      "HARD": (88, 10), "AVGWT": (300, 5), "TAMC": (60, 70), "LOD": (1.2, 0.3), "PH": (7.4, 0.06),
                      "OSMO": (295, 5), "FILLVOL": (503, 2.6)}[kw]
    v = max(0.0, rnd.gauss(centre + bias, spread))
    return round(v, 0 if kw in ("TAMC", "DISS", "HARD", "OSMO") else 2)


def available(mid, d):
    return sorted((b for b in batches.values() if b["material_id"] == mid and b["status"] == "Released"
                   and b["on_hand"] > 1e-9 and b["expiry"] > d), key=lambda b: b["expiry"])


def missing_stock(recipe, d):
    """First material the run cannot be supplied with, or None."""
    return next((m for m, q in recipe if sum(b["on_hand"] for b in available(m, d)) < q), None)


def consume(recipe, d, ts, exec_id):
    used = []
    for mid, q in recipe:
        for b in available(mid, d):
            take = min(q, b["on_hand"])
            b["on_hand"] -= take
            q -= take
            consumption.append([exec_id, b["batch_id"], mid, round(take, 4), MAT[mid][2]])
            move(b["batch_id"], mid, "Consumption", -take, ts, exec_id)
            used.append(b["batch_id"])
            if q <= 1e-9:
                break
    return used


# --- process order schedule -------------------------------------------------------------------
o_no = 1000000
d = START
while d < END:
    for mid, per_week, line, size in (("P2002", 4, "Line 1", 300000), ("P1001", 3, "Line 2", 8000)):
        n = per_week + (2 if mid == "P2002" and date(2026, 9, 1) <= d < date(2026, 10, 1) else 0)
        for _ in range(n):
            day = workday(d + timedelta(days=rnd.randint(0, 4)))
            if day < END:
                o_no += 1
                orders.append([o_no, mid, MAT[mid][0], line, day, size, MAT[mid][2]])
    d += timedelta(days=7)
orders_by_day = defaultdict(list)
for o in orders:
    orders_by_day[o[4]].append(o)

# --- day-by-day simulation --------------------------------------------------------------------
d = WARMUP
while d < END:
    # 1. procurement: raw materials on a rough cadence, lab stock by reorder point (Mondays)
    if d.weekday() == 0:
        for mid, m in MAT.items():
            if m[1] == "Lab stock":
                stock = sum(b["on_hand"] for b in batches.values() if b["material_id"] == mid and b["status"] == "Released")
                if stock + open_po[mid] < m[6] * (1.6 if d >= date(2026, 9, 1) else 1.0) or (d == WARMUP):
                    raise_po(mid, d)
    # 2. goods receipts -> stock batches (raw materials quarantined and sampled)
    for po, sid, mid, q in due.pop(d, []):
        gr_no += 1
        bid = f"{mid}-{d:%y%m%d}-{gr_no:03d}"
        gr = f"GR{gr_no:05d}"
        if mid == "L07" and BAD_TSA is None and d >= date(2026, 9, 1):
            BAD_TSA = bid
        batches[bid] = dict(batch_id=bid, material_id=mid, supplier_id=sid, receipt_id=gr, received=d,
                            expiry=d + timedelta(days=MAT[mid][7]), qty=q, on_hand=q,
                            status="Released", supplier_lot=f"{sid}-L{rnd.randint(10000, 99999)}")
        receipts.append([gr, po, sid, mid, d, q, bid])
        open_po[mid] -= q
        move(bid, mid, "Goods receipt", q, at(d, 9), gr)
    if d >= START and d.weekday() < 5:
        # 3. process orders trigger in-process and release sampling plans
        for o in orders_by_day.get(d, []):
            for plan in PLANS_BY_MAT[o[1]]:
                for i in range(plan[5]):
                    if "IPC" in plan[0]:
                        t = at(d, 8) + timedelta(hours=(i + 1) * 3)
                        log_sample(plan, str(o[0]), at(d, 7), t)
                    else:
                        log_sample(plan, str(o[0]), at(d, 7), at(workday(d + timedelta(days=1)), 8, 30))
        # 4. lab work: FIFO queue, analysts' minutes, stock must be available
        clock = {a: at(d, 8) for grp in ANALYSTS.values() for a in grp}
        budget = {a: MINUTES_PER_DAY[g] if present(a, d) else 0 for g, grp in ANALYSTS.items() for a in grp}
        capacity = dict(budget)
        queue.sort(key=lambda aid: samples[analyses[aid]["sample_id"]]["received_ts"])
        waiting = []
        for aid in queue:
            a = analyses[aid]
            s = samples[a["sample_id"]]
            if s["received_ts"] > at(d, 15):
                waiting.append(aid)
                continue
            proto, mins, elapsed, instr, grp, recipe = PROTOCOLS[a["keyword"]]
            who = max(ANALYSTS[grp], key=lambda x: budget[x])
            actual = max(3, round(mins * speed(who, d) * rnd.gauss(1, 0.08)))
            short = missing_stock(recipe, d)
            if short or budget[who] < actual:
                a["blocked"] = ("Waiting for stock", short) if short else ("Waiting for analyst", None)
                waits.append([d, aid, a["sample_id"], a["keyword"], a["blocked"][0], short or ""])
                waiting.append(aid)
                continue
            start = max(clock[who], s["received_ts"])
            e_no += 1
            eid = f"EX{e_no:06d}"
            used = consume(recipe, d, start, eid)
            a["attempts"] += 1
            status = "Completed"
            if a["keyword"] in ("TAMC", "ECOLI") and BAD_TSA in used and rnd.random() < 0.6:
                status = "Aborted - growth promotion failure"
                gp_failures[BAD_TSA] += 1
                if gp_failures[BAD_TSA] == 4:  # lab investigates and blocks the media lot in ERP
                    batches[BAD_TSA]["status"] = "Blocked"
                    move(BAD_TSA, "L07", "Blocked - investigation", 0, end_of_day := at(d, 17), "deviation DEV-2026-041")
            elif instr == "HPLC" and rnd.random() < 0.02:
                status = "Aborted - system suitability failure"
            elif rnd.random() < PEOPLE[who]["error"] * (1 + 2 * max(0.0, speed(who, d) - 1.05) / 0.3):
                status = "Aborted - analyst error"
            end = start + timedelta(minutes=elapsed)
            executions.append([eid, aid, a["sample_id"], a["keyword"], proto, s["received_ts"], who, instr + ("-0" + str(rnd.randint(1, 2)) if instr == "HPLC" else ""),
                               start, end, mins, actual, status, a["attempts"]])
            runs_by_sample[a["sample_id"]].append((start, end))
            clock[who] = start + timedelta(minutes=actual)
            budget[who] -= actual
            if status != "Completed":
                a["blocked"] = ("Repeat after aborted run", None)
                waits.append([d, aid, a["sample_id"], a["keyword"], "Repeat after aborted run", ""])
                waiting.append(aid)
                continue
            a["blocked"] = None
            v = value(a["keyword"], s)
            lo, hi = a["spec_min"], a["spec_max"]
            a.update(result=v, out_of_spec=(lo is not None and v < lo) or (hi is not None and v > hi),
                     status="to_be_verified", completed_ts=end, execution_id=eid)
        queue[:] = waiting
        # 5. results complete -> QC review queue in LIMS; reviewers verify FIFO within their daily minutes
        for smp in samples.values():
            if smp["status"] == "received" and smp["completed_ts"] is None:
                done = [analyses[x] for x in smp["analyses"]]
                if all(x["completed_ts"] and x["completed_ts"] <= at(d, 16) for x in done):
                    smp["completed_ts"] = max(x["completed_ts"] for x in done)
                    busy, cur = timedelta(0), None  # union of run intervals = time something was on test
                    for st, en in sorted(runs_by_sample[smp["sample_id"]]):
                        if cur and st <= cur[1]:
                            cur = (cur[0], max(cur[1], en))
                        else:
                            busy += (cur[1] - cur[0]) if cur else timedelta(0)
                            cur = (st, en)
                    busy += (cur[1] - cur[0]) if cur else timedelta(0)
                    smp["in_test_hours"] = round(busy.total_seconds() / 3600, 2)
                    smp["queued_hours"] = round((smp["completed_ts"] - smp["received_ts"] - busy).total_seconds() / 3600, 2)
                    smp["out_of_spec"] = any(x["out_of_spec"] for x in done)
                    review_queue.append(smp["sample_id"])
        rclock = {r: at(d, 13) for r in REVIEWERS}  # review block after lunch
        rbudget = {r: MINUTES_PER_DAY["review"] if present(r, d) else 0 for r in REVIEWERS}
        for r in REVIEWERS:
            capacity[r] = rbudget[r]
        review_queue.sort(key=lambda x: samples[x]["completed_ts"])
        left = []
        for sid in review_queue:
            smp = samples[sid]
            n = len(smp["analyses"])
            mins = max(4, round((10 + 4 * n + (30 if smp["out_of_spec"] else 0)) * rnd.gauss(1, 0.15)))
            r = max(REVIEWERS, key=lambda x: rbudget[x])
            if rbudget[r] < mins or smp["completed_ts"] > at(d, 12):
                left.append(sid)
                continue
            start = max(rclock[r], smp["completed_ts"])
            smp.update(review_start_ts=start, verified_ts=start + timedelta(minutes=mins), reviewer=r,
                       review_minutes=mins, status="verified")
            for x in smp["analyses"]:
                analyses[x]["status"] = "verified"
            rclock[r] = start + timedelta(minutes=mins)
            rbudget[r] -= mins
        review_queue[:] = left
        for person, cap in capacity.items():
            person_days.append([d, person, PEOPLE[person]["role"], cap, cap - (budget.get(person, rbudget.get(person)))])
        # 6. end-of-day snapshot: where every open analysis is sitting
        eod = at(d, 18)
        wip = defaultdict(int)
        for smp in samples.values():
            if smp["status"] != "received" or smp["received_ts"] > eod:
                continue
            all_done = all(analyses[i]["completed_ts"] and analyses[i]["completed_ts"] <= eod for i in smp["analyses"])
            for x in (analyses[i] for i in smp["analyses"]):
                if x["completed_ts"] is None:
                    state = (x.get("blocked") or ("Waiting for analyst", None))[0]
                elif x["completed_ts"] > eod:
                    state = "In test / incubation"
                elif all_done:
                    state = "Awaiting QC review"
                else:
                    state = "Done, waiting on other tests"
                wip[state] += 1
        for state, n in wip.items():
            daily_wip.append([d, state, n])
    # 7. expiry write-offs
    for b in batches.values():
        if b["status"] == "Released" and b["expiry"] == d and b["on_hand"] > 0:
            move(b["batch_id"], b["material_id"], "Expired write-off", -b["on_hand"], at(d, 23), "")
            b["on_hand"], b["status"] = 0, "Expired"
    d += timedelta(days=1)


# --- write CSVs -----------------------------------------------------------------------------
def fmt(c):
    if isinstance(c, datetime):
        return c.strftime("%Y-%m-%d %H:%M")
    return "" if c is None else c


def write(name, header, rows):
    with open(os.path.join(args.out, name + ".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows([[fmt(c) for c in r] for r in rows])
    print(f"{name:24s} {len(rows):6d} rows")


for old in os.listdir(args.out):
    if old.endswith(".csv"):
        os.remove(os.path.join(args.out, old))
write("erp_materials", ["material_id", "name", "material_type", "uom", "shelf_life_days"],
      [[k, m[0], m[1], m[2], m[7]] for k, m in MAT.items()])
write("erp_stock_batches", ["batch_id", "material_id", "received_date", "expiry_date", "quantity_received", "quantity_on_hand", "status"],
      [[b["batch_id"], b["material_id"], b["received"], b["expiry"], b["qty"], round(b["on_hand"], 4), b["status"]]
       for b in batches.values()])
write("erp_inventory_movements", ["movement_id", "batch_id", "material_id", "movement_type", "quantity", "posted_ts", "reference"], movements)
write("erp_process_orders", ["order_id", "material_id", "product", "line", "order_date", "quantity", "uom"], orders)
write("erp_sampling_plans", ["plan_id", "trigger", "material_id", "sample_type", "sample_point", "samples_per_trigger", "analyses"],
      [list(pl[:6]) + [" ".join(pl[6])] for pl in PLANS])
write("lims_specifications", ["keyword", "test", "unit", "spec_min", "spec_max"], [[k, *v] for k, v in TESTS.items()])
write("lims_samples", ["sample_id", "plan_id", "trigger", "trigger_ref", "material_id", "sample_type", "sample_point",
                       "logged_ts", "received_ts", "results_complete_ts", "review_start_ts", "verified_ts", "reviewer",
                       "review_minutes", "status", "out_of_spec", "queued_hours", "in_test_hours"],
      [[s[k] for k in ("sample_id", "plan_id", "trigger", "trigger_ref", "material_id", "sample_type", "sample_point",
                       "logged_ts", "received_ts", "completed_ts", "review_start_ts", "verified_ts", "reviewer",
                       "review_minutes", "status", "out_of_spec")] + [s.get("queued_hours"), s.get("in_test_hours")]
      for s in samples.values()])
write("lims_analyses", ["analysis_id", "sample_id", "keyword", "test", "unit", "spec_min", "spec_max", "result", "out_of_spec",
                        "status", "completed_ts", "execution_id"],
      [[a.get(k) for k in ("analysis_id", "sample_id", "keyword", "test", "unit", "spec_min", "spec_max", "result",
                           "out_of_spec", "status", "completed_ts", "execution_id")] for a in analyses.values()])
write("mes_protocols", ["protocol_id", "keyword", "analyst_minutes", "elapsed_minutes", "instrument", "lab_area"],
      sorted({(v[0], k, v[1], v[2], v[3], v[4]) for k, v in PROTOCOLS.items()}))
write("mes_protocol_materials", ["keyword", "material_id", "quantity_per_run"],
      [[k, m, q] for k, v in PROTOCOLS.items() for m, q in v[5]])
write("mes_executions", ["execution_id", "analysis_id", "sample_id", "keyword", "protocol_id", "work_order_ts", "analyst", "instrument",
                         "start_ts", "end_ts", "standard_minutes", "actual_minutes", "status", "attempt"], executions)
write("mes_consumption", ["execution_id", "batch_id", "material_id", "quantity", "uom"], consumption)
write("lims_wait_events", ["day", "analysis_id", "sample_id", "keyword", "reason", "material_id"], waits)
write("lims_daily_wip", ["day", "state", "open_analyses"], daily_wip)
write("qc_person_days", ["day", "person", "role", "available_minutes", "booked_minutes"], person_days)
write("qc_people", ["person", "role", "lab_area", "start_date"],
      [[n, p["role"], p.get("area", "review"), p["start"]] for n, p in PEOPLE.items()])
print("bad TSA lot:", BAD_TSA)
