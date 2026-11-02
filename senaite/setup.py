"""Seed SENAITE with a manufacturing-QC demo: SKUs, tests, specs, plans, samples.

Idempotent per title: re-running skips anything that already exists.
Run: SENAITE_PASSWORD=... python3 setup.py
"""
from datetime import datetime, timedelta

from sapi import call, ensure, find, set_refs

SETUP = "/senaite/setup"
BIKA = "/senaite/bika_setup"


def uid_of(portal_type, title):
    return find(portal_type, title)["uid"]


# --- Lab name (global Setup is not API-editable; self-verification is per test) --
lab = call("search?portal_type=Laboratory&complete=no")["items"][0]["uid"]
try:
    call("update", {"uid": lab, "title": "Demo QC Laboratory"})
except RuntimeError as e:
    print("lab rename skipped:", e)

# --- People -----------------------------------------------------------------
LC = BIKA + "/bika_labcontacts"
manager = ensure("LabContact", LC, "Mark Manager", Firstname="Mark", Surname="Manager",
                 JobTitle="QC Manager", EmailAddress="qc.manager@example.com")
ensure("LabContact", LC, "Anna Analyst", Firstname="Anna", Surname="Analyst",
       JobTitle="QC Analyst", EmailAddress="qc.analyst@example.com")

# --- Departments & categories ----------------------------------------------
dept = {}
for title, code in [("Chemistry", "CHEM"), ("Microbiology", "MICRO"),
                    ("Physical Testing", "PHYS")]:
    dept[code] = ensure("Department", SETUP + "/departments", title,
                        department_id=code, manager=manager)

cat = {}
for title, d, key in [("Physical", "PHYS", 1), ("Identification", "CHEM", 2),
                      ("Chemical", "CHEM", 3), ("Microbiological", "MICRO", 4)]:
    cat[title] = ensure("AnalysisCategory", SETUP + "/analysiscategories", title,
                        department=dept[d], sort_key=key)

# --- Methods ----------------------------------------------------------------
meth = {}
for key, title in [
        ("VIS", "Visual inspection (SOP-QC-001)"),
        ("IR", "FTIR identification (USP <197>)"),
        ("PH", "pH potentiometric (USP <791>)"),
        ("HPLC", "HPLC assay & related substances (SOP-QC-014)"),
        ("KF", "Karl Fischer titration (USP <921>)"),
        ("LOD", "Loss on drying (USP <731>)"),
        ("DISS", "Dissolution, apparatus 2 (USP <711>)"),
        ("PHYS", "Tablet physical tests (USP <1217>, <905>)"),
        ("OSMO", "Osmolality (USP <785>)"),
        ("MICRO", "Microbial enumeration & specified organisms (USP <61>/<62>)")]:
    meth[key] = ensure("Method", "/senaite/methods", title)

# --- Analysis services (tests) ---------------------------------------------
CONFORMS = [{"ResultValue": "1", "ResultText": "Conforms"},
            {"ResultValue": "0", "ResultText": "Does not conform"}]
SVC = BIKA + "/bika_analysisservices"
services = [
    # title, keyword, category, department, method, unit, precision, select-options
    ("Appearance", "APPEAR", "Physical", "PHYS", "VIS", "", 0, CONFORMS),
    ("Colour of solution", "COLOUR", "Physical", "PHYS", "VIS", "", 0,
     [{"ResultValue": "1", "ResultText": "Clear, colourless"},
      {"ResultValue": "2", "ResultText": "Slightly yellow"},
      {"ResultValue": "3", "ResultText": "Yellow / turbid"}]),
    ("Identification (FTIR)", "ID_IR", "Identification", "CHEM", "IR", "", 0,
     [{"ResultValue": "1", "ResultText": "Positive - matches reference"},
      {"ResultValue": "0", "ResultText": "Negative"}]),
    ("pH", "PH", "Chemical", "CHEM", "PH", "", 2, None),
    ("Assay", "ASSAY", "Chemical", "CHEM", "HPLC", "% label claim", 1, None),
    ("Total impurities", "IMPTOT", "Chemical", "CHEM", "HPLC", "%", 2, None),
    ("Water content (KF)", "WATER", "Chemical", "CHEM", "KF", "% w/w", 2, None),
    ("Loss on drying", "LOD", "Chemical", "CHEM", "LOD", "% w/w", 2, None),
    ("Dissolution (30 min)", "DISS", "Chemical", "CHEM", "DISS", "% dissolved", 0, None),
    ("Osmolality", "OSMO", "Chemical", "CHEM", "OSMO", "mOsm/kg", 0, None),
    ("Tablet hardness", "HARD", "Physical", "PHYS", "PHYS", "N", 0, None),
    ("Average tablet weight", "AVGWT", "Physical", "PHYS", "PHYS", "mg", 1, None),
    ("Fill volume", "FILLVOL", "Physical", "PHYS", "VIS", "mL", 1, None),
    ("Total aerobic microbial count", "TAMC", "Microbiological", "MICRO", "MICRO", "CFU/g", 0, None),
    ("Total yeasts & moulds count", "TYMC", "Microbiological", "MICRO", "MICRO", "CFU/g", 0, None),
    ("Escherichia coli", "ECOLI", "Microbiological", "MICRO", "MICRO", "", 0,
     [{"ResultValue": "0", "ResultText": "Absent in 1 g"},
      {"ResultValue": "1", "ResultText": "Present"}]),
]
svc = {}
for title, kw, c, d, m, unit, prec, opts in services:
    fields = dict(Keyword=kw, Category=cat[c], Department=dept[d],
                  Methods=[meth[m]], Method=meth[m], Unit=unit, Precision=prec,
                  SelfVerification=1)
    if opts:
        fields.update(ResultType="select", ResultOptions=opts)
    svc[kw] = ensure("AnalysisService", SVC, title, **fields)

# --- SKUs (sample types) ----------------------------------------------------
ST = SETUP + "/sampletypes"
sku = {
    "IBU": ensure("SampleType", ST, "SKU-2002 Ibuprofen 200 mg tablets", prefix="IBU",
                  min_volume="60 tablets", description="Finished product, blister 20s"),
    "GRAN": ensure("SampleType", ST, "SKU-2002-G Ibuprofen granulate (in-process)",
                   prefix="GRAN", min_volume="50 g", description="In-process control"),
    "PB": ensure("SampleType", ST, "SKU-1001 Phosphate buffer pH 7.4, 500 mL", prefix="PB",
                 min_volume="3 bottles", description="Finished product, sterile solution"),
    "NACL": ensure("SampleType", ST, "SKU-3003 Sodium chloride USP (raw material)",
                   prefix="NACL", min_volume="100 g", description="Incoming raw material"),
}

# --- Sample points ----------------------------------------------------------
SP = SETUP + "/samplepoints"
spt = {}
for key, title, st in [("RM", "RM warehouse - sampling booth", "NACL"),
                       ("GRAN", "Line 1 - fluid-bed dryer outlet", "GRAN"),
                       ("COMP", "Line 1 - tablet press discharge", "IBU"),
                       ("FILL", "Line 2 - filling machine", "PB")]:
    spt[key] = ensure("SamplePoint", SP, title)
    # Only the AT-style name with a scalar UID sticks ("sample_types" / lists are ignored)
    set_refs(spt[key], {"SampleTypes": sku[st]})

# --- Specifications (limits per SKU) -----------------------------------------
def rr(kw, lo, hi, wlo="", whi="", comment=""):
    return {"keyword": kw, "uid": svc[kw], "min": str(lo), "max": str(hi),
            "warn_min": str(wlo), "warn_max": str(whi),
            "min_operator": "geq", "max_operator": "leq", "rangecomment": comment}

specs = {
    "IBU": [rr("APPEAR", 1, 1, comment="White, round, biconvex"), rr("ID_IR", 1, 1),
            rr("ASSAY", 95.0, 105.0, 96.0, 104.0), rr("IMPTOT", 0, 0.5, "", 0.4),
            rr("DISS", 80, 110, comment="Q = 75% + 5"), rr("WATER", 0, 2.0),
            rr("HARD", 60, 120), rr("AVGWT", 285, 315, 290, 310),
            rr("TAMC", 0, 1000, comment="NMT 10^3 CFU/g"), rr("TYMC", 0, 100),
            rr("ECOLI", 0, 0, comment="Absent in 1 g")],
    "GRAN": [rr("APPEAR", 1, 1), rr("LOD", 1.0, 2.5, 1.2, 2.3)],
    "PB": [rr("APPEAR", 1, 1), rr("COLOUR", 1, 1), rr("PH", 7.30, 7.50, 7.32, 7.48),
           rr("OSMO", 280, 320), rr("FILLVOL", 500, 510), rr("TAMC", 0, 100),
           rr("ECOLI", 0, 0)],
    "NACL": [rr("APPEAR", 1, 1, comment="White crystalline powder"), rr("ID_IR", 1, 1),
             rr("ASSAY", 99.0, 100.5), rr("LOD", 0, 0.5), rr("PH", 4.5, 7.0, comment="5% solution")],
}
SPEC_TITLES = {"IBU": "Release spec - SKU-2002 Ibuprofen 200 mg tablets",
               "GRAN": "IPC spec - SKU-2002-G granulate",
               "PB": "Release spec - SKU-1001 Phosphate buffer pH 7.4",
               "NACL": "Acceptance spec - SKU-3003 Sodium chloride USP"}
spec = {k: ensure("AnalysisSpec", BIKA + "/bika_analysisspecs", SPEC_TITLES[k],
                  SampleType=sku[k], ResultsRange=specs[k]) for k in specs}

# --- Test panels (analysis profiles) ----------------------------------------
def svcs(*kws):
    return [{"uid": svc[k], "hidden": False} for k in kws]

AP = SETUP + "/analysisprofiles"
# profile_key is set after create: on create the uniqueness invariant matches the new
# profile against itself (SENAITE 2.6 bug).
for title, key, extra in [
        ("Micro panel (TAMC / TYMC / E. coli)", "PNL-MICRO",
         dict(services=svcs("TAMC", "TYMC", "ECOLI"))),
        ("Ibuprofen tablets - chemical release", "PNL-IBU-CHEM",
         dict(sample_types=[sku["IBU"]],
              services=svcs("APPEAR", "ID_IR", "ASSAY", "IMPTOT", "DISS", "WATER", "HARD", "AVGWT")))]:
    p = ensure("AnalysisProfile", AP, title, **extra)
    if call("AnalysisProfile/" + p)["items"][0].get("profile_key") != key:
        call("update", {"uid": p, "profile_key": key})

# --- Sampling plans (sample templates) --------------------------------------
# Create with plain fields, then set refs/partitions one by one: the API stores them
# but answers 400 with empty messages, and lowercase ref names are silently ignored.
TPL = SETUP + "/sampletemplates"
MICRO = ("TAMC", "TYMC", "ECOLI")


def plan(key, title, desc, point, kws, parts=None, composite=False):
    services = [{"uid": svc[k], "hidden": False,
                 "part_id": ("part-2" if k in MICRO else "part-1") if parts else ""}
                for k in kws]
    uid = ensure("SampleTemplate", TPL, title, description=desc, composite=composite,
                 services=services)
    refs = {"SampleType": sku[key], "SamplePoint": spt[point]}
    if parts:
        refs["partitions"] = [{"part_id": p, "container": "", "preservation": "",
                               "sampletype": sku[key]} for p in parts]
    set_refs(uid, refs)
    return uid


tpl = {
    "IBU": plan("IBU", "Batch release plan - SKU-2002 tablets",
                "60 tablets from press discharge (begin/middle/end of run). "
                "Part 1 chemistry, part 2 microbiology.", "COMP",
                ("APPEAR", "ID_IR", "ASSAY", "IMPTOT", "DISS", "WATER", "HARD", "AVGWT") + MICRO,
                parts=["part-1", "part-2"]),
    "GRAN": plan("GRAN", "IPC plan - granulate LOD every dryer load",
                 "1 x 50 g per dryer load, sampled at dryer outlet.", "GRAN", ("APPEAR", "LOD")),
    "PB": plan("PB", "Batch release plan - SKU-1001 buffer",
               "3 bottles: start, middle, end of fill.", "FILL",
               ("APPEAR", "COLOUR", "PH", "OSMO", "FILLVOL", "TAMC", "ECOLI")),
    "NACL": plan("NACL", "Incoming RM plan - SKU-3003 (sqrt(n)+1 containers)",
                 "Sample sqrt(n)+1 containers of the delivery, composite for assay.", "RM",
                 ("APPEAR", "ID_IR", "ASSAY", "LOD", "PH"), composite=True),
}

# --- Client (the production site that requests testing) ---------------------
client = ensure("Client", "/senaite/clients", "Production - Plant 1", ClientID="PLANT1",
                EmailAddress="production@example.com")
client_path = call("Client/" + client)["items"][0]["path"]
contact = ensure("Contact", client_path, "Paul Planner", Firstname="Paul", Surname="Planner",
                 EmailAddress="planner@example.com", JobTitle="Production planner")

print("setup OK:", len(svc), "tests,", len(sku), "SKUs,", len(spec), "specs,", len(tpl), "plans")
