"""
Tests for src/agent/evaluate_claim.py (Rekha).   Run from the repo root:  python test_evaluate_claim.py

If `duckdb` is installed it uses the real priorauth.duckdb (after `python setup_duckdb.py`).
Otherwise it loads the same CSVs into in-memory SQLite: the SQL in load_case() uses plain
`?` placeholders, so the same queries run on both. Saves sample outputs under analysis/.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src" / "agent"))
import evaluate_claim as ev  # noqa: E402

FAILED = []


def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILED.append(label)


def get_connection():
    try:
        import duckdb
        if ev.DB_PATH.exists():
            print(f"(using DuckDB: {ev.DB_PATH})")
            return duckdb.connect(str(ev.DB_PATH), read_only=False)
    except ImportError:
        pass
    import sqlite3
    import pandas as pd
    print("(using in-memory SQLite loaded from data/*.csv -- same SQL as DuckDB)")
    con = sqlite3.connect(":memory:")
    pd.read_csv(ROOT / "data" / "patients_sample.csv").to_sql("patients", con, index=False)
    pd.read_csv(ROOT / "data" / "claims_sample.csv").to_sql("claims", con, index=False)
    return con


def rule(res, rid):
    return next((r for r in res["rules"] if r["rule_id"] == rid), None)


con = get_connection()
R1, R2, R3 = "r1_conservative_or_red_flag", "r2_radiculopathy_dx_or_red_flag", "r3_adult_age"
out = {}

print("\n== John, C10001 (SampleCommercial, CA, 72149, 3 weeks, no red flag)")
j = out["john"] = ev.evaluate_claim("C10001", con=con)
check("decision DOES_NOT_MEET_CRITERIA", j["decision"] == ev.DOES_NOT_MEET)
check("Rule 1 FAIL", rule(j, R1)["result"] == "FAIL")
check("routed to human_review", j["routing"] == "human_review")
check("commercial claim has no radiculopathy rule", rule(j, R2) is None)
check("Rule 1 cites commercial medical_necessity_criteria",
      rule(j, R1)["cites_chunk"] == ["commercial_lumbar_mri::medical_necessity_criteria"])
check("age rule labeled team_assumption, no citation",
      rule(j, R3)["basis"] == "team_assumption" and rule(j, R3)["cites_chunk"] == [])
check("policy attached is commercial_lumbar_mri", j["policy"]["policy_id"] == "commercial_lumbar_mri")
check("72149 assumption is listed as a team assumption",
      any("72149" in n["item"] and n["basis"] == "team_assumption" for n in j["not_evaluated"]))

print("\n== Red-flag exception, commercial (C10286: 72148, 3 weeks, red flag)")
rf = out["red_flag_commercial"] = ev.evaluate_claim("C10286", con=con)
check("Rule 1 PASS via red-flag exception",
      rule(rf, R1)["result"] == "PASS" and rule(rf, R1)["via"] == "red_flag_exception")
check("decision MEETS_CRITERIA, ready_to_submit", rf["decision"] == ev.MEETS and rf["routing"] == "ready_to_submit")

print("\n== Commercial, 72148, passes on weeks (C10006, 12 weeks)")
cm = out["commercial"] = ev.evaluate_claim("C10006", con=con)
check("cites commercial policy", cm["policy"]["policy_id"] == "commercial_lumbar_mri"
      and cm["policy"]["jurisdiction"] == "national")
check("MEETS_CRITERIA", cm["decision"] == ev.MEETS)

print("\n== Medicare, plan-style John (C10203: NY, 72148, M51.16, 3 weeks, no red flag)")
mj = out["medicare_john"] = ev.evaluate_claim("C10203", con=con)
check("Medicare LCD, region JK", mj["policy"]["policy_id"] == "medicare_lcd_lumbar_mri"
      and mj["policy"]["jurisdiction"] == "JK")
check("Rule 1 FAIL, Rule 2 PASS", rule(mj, R1)["result"] == "FAIL" and rule(mj, R2)["result"] == "PASS")
check("DOES_NOT_MEET_CRITERIA -> human_review", mj["decision"] == ev.DOES_NOT_MEET and mj["routing"] == "human_review")

print("\n== Diagnosis history (C10009: P1002, claim dx M53.0, earlier claims have a radiculopathy code)")
h = out["history"] = ev.evaluate_claim("C10009", con=con)
own_dx_is_radic = "M53.0" in ("M54.16", "M54.17", "M51.16")   # the claim's own dx is M53.0 -> False
check("Rule 2 PASS only because of the patient's history (claim's own dx is not a radiculopathy code)",
      rule(h, R2)["result"] == "PASS" and not own_dx_is_radic and any(
          c in ("M54.16", "M54.17", "M51.16") for c in h["inputs"]["diagnosis_codes"]))
check("history excludes later claims",
      all(c in ("M42.90", "M47.91", "M51.16", "M53.0", "M54.16", "M54.17") for c in h["inputs"]["diagnosis_codes"]))

print("\n== Medicare red-flag exception on Rule 2 (C10284: dx M47.91, red flag, 7 weeks)")
m2 = out["medicare_rule2_exception"] = ev.evaluate_claim("C10284", con=con)
check("Rule 2 PASS via red-flag exception", rule(m2, R2)["result"] == "PASS" and rule(m2, R2)["via"] == "red_flag_exception")
check("MEETS_CRITERIA", m2["decision"] == ev.MEETS)

print("\n== No policy")
retrieve = ev._import_retrieve_policy()
case = {"claim_id": "TEST-NOPOLICY", "patient_id": "PX", "procedure_code": "72148", "payer": "Medicare",
        "state": "CA", "patient_age": 60, "diagnosis_codes": ["M54.16"],
        "conservative_treatment_weeks": 8, "red_flag_present": False}
np_ = out["no_policy"] = ev.evaluate_case(case, retrieve("72148", "Medicare", "CA"))
check("policy found = false", np_["policy"]["found"] is False)
check("routed to human_review, no rules run", np_["routing"] == "human_review" and np_["rules"] == [])
check("reason says it is not 'no requirements'", "does not mean" in np_["decision_reason"])
ov = out["office_visit"] = ev.evaluate_claim("C10000", con=con)
check("office visit 99214 -> human_review, cannot assess", ov["routing"] == "human_review" and ov["rules"] == [])

print("\n== Missing data and the team-assumption rule (synthetic cases)")
base = dict(case, state="MA", claim_id="T1")
pol = retrieve("72148", "Medicare", "MA")
miss = ev.evaluate_case(dict(base, conservative_treatment_weeks=None), pol)
check("missing weeks -> NEEDS_DOCS + request_documentation",
      miss["decision"] == ev.NEEDS_DOCS and miss["routing"] == "request_documentation")
young = ev.evaluate_case(dict(base, patient_age=16), pol)
check("fails ONLY the age assumption -> human_review, not DOES_NOT_MEET",
      young["decision"] != ev.DOES_NOT_MEET and young["routing"] == "human_review")
check("age rule shown as FAIL with team_assumption basis",
      rule(young, R3)["result"] == "FAIL" and rule(young, R3)["basis"] == "team_assumption")
check("claim not found handled", ev.evaluate_claim("C99999", con=con)["routing"] == "human_review")

print("\n== Whole dataset: every claim runs, wording and citations hold")
ids = [r[0] for r in con.execute("SELECT claim_id FROM claims ORDER BY claim_id").fetchall()]
tally, bad_words, bad_cites, errors = {}, [], [], []
for cid in ids:
    try:
        r = ev.evaluate_claim(cid, con=con)
    except Exception as e:  # noqa: BLE001
        errors.append((cid, repr(e)))
        continue
    tally[(r["decision"], r["routing"])] = tally.get((r["decision"], r["routing"]), 0) + 1
    agent_output = {k: v for k, v in r.items() if k != "policy"}   # policy text is quoted, not agent wording
    if re.search(r"\b(approved?|denied|denies|denial)\b", json.dumps(agent_output, default=str), re.I):
        bad_words.append(cid)
    if r["warnings"]:
        bad_cites.append(cid)
check(f"all {len(ids)} claims evaluated without error", not errors and len(ids) == 313)
check("no 'approved/denied' wording in anything the agent writes", not bad_words)
check("every cited chunk appears in the retrieved policy (all claims)", not bad_cites)
for k, v in sorted(tally.items()):
    print(f"      {k[0]:24} {k[1]:22} {v}")

adir = ROOT / "analysis"
adir.mkdir(exist_ok=True)
for name, fname in [("john", "evaluate_claim_john"), ("red_flag_commercial", "evaluate_claim_red_flag"),
                    ("commercial", "evaluate_claim_commercial"), ("medicare_john", "evaluate_claim_medicare"),
                    ("no_policy", "evaluate_claim_no_policy")]:
    (adir / f"{fname}.json").write_text(json.dumps(out[name], indent=2, default=str), encoding="utf-8")
print("\nSaved sample outputs to analysis/evaluate_claim_*.json")

print("\nFAILED:" if FAILED else "\nALL CHECKS PASSED")
for f in FAILED:
    print("  -", f)
sys.exit(1 if FAILED else 0)
