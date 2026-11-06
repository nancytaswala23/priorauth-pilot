#!/usr/bin/env python3
"""
preflight_check.py -- one command that checks the whole PriorAuthPilot demo
(Nancy's data + app, Yashasvi's retrieval, Rekha's evaluation).

Run from the repo root, with the Streamlit app STOPPED (Ctrl+C in its terminal):

    python3 preflight_check.py

It cannot click through the browser. After it passes, do the short on-screen
checklist (see the end of its output).
"""
import ast
import os
import py_compile
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src" / "agent"))
sys.path.insert(0, str(ROOT / "src" / "rag"))

COUNT = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}


def rep(status, label, note=""):
    COUNT[status] += 1
    print(f"  [{status}] {label}" + (f"  -- {note}" if note else ""))


def check(cond, label, note_if_fail=""):
    rep("PASS" if cond else "FAIL", label, "" if cond else note_if_fail)
    return cond


def head(title):
    print(f"\n=== {title}")


# ---------------------------------------------------------------- database
def open_db():
    """The real DuckDB file if possible, otherwise the CSVs in SQLite (same SQL)."""
    db_path = ROOT / "priorauth.duckdb"
    try:
        import duckdb
    except ImportError:
        duckdb = None
        rep("WARN", "duckdb is not installed", "run: python3 -m pip install -r requirements.txt")
    if duckdb and db_path.exists():
        try:
            return duckdb.connect(str(db_path)), "duckdb"
        except Exception as e:  # noqa: BLE001
            rep("FAIL", "could not open priorauth.duckdb",
                f"{str(e)[:90]} -- is the Streamlit app still running? Press Ctrl+C in its terminal")
    elif duckdb:
        rep("FAIL", "priorauth.duckdb not found", "run: python3 setup_duckdb.py && python3 add_procedures.py")
    import sqlite3
    import pandas as pd
    rep("WARN", "using the CSV files in SQLite instead of the real DuckDB file (results below are less conclusive)")
    con = sqlite3.connect(":memory:")
    pd.read_csv(ROOT / "data" / "patients_sample.csv").to_sql("patients", con, index=False)
    pd.read_csv(ROOT / "data" / "claims_sample.csv").to_sql("claims", con, index=False)
    return con, "sqlite"


def one(con, sql, params=()):
    return con.execute(sql, list(params)).fetchone()


def all_(con, sql):
    return con.execute(sql).fetchall()


# ------------------------------------------------------------ Nancy: data
def check_data(con, kind):
    head("NANCY - data layer (DuckDB)")
    counts = {}
    for table, want in [("patients", 100), ("claims", 313), ("procedures", 5), ("policies", 14)]:
        try:
            counts[table] = one(con, f"SELECT COUNT(*) FROM {table}")[0]
            check(counts[table] == want, f"table {table}: {counts[table]} rows (expected {want})")
        except Exception:  # noqa: BLE001
            if kind == "sqlite" and table in ("procedures", "policies"):
                rep("SKIP", f"table {table}", "not in the CSV fallback")
            else:
                rep("FAIL", f"table {table} is missing", "run: python3 setup_duckdb.py && python3 add_procedures.py")
    if kind == "duckdb":
        t = one(con, "SELECT typeof(red_flag_present) FROM claims LIMIT 1")[0]
        check(str(t).upper() == "BOOLEAN", f"claims.red_flag_present is {t} (expected BOOLEAN)")
    payers = {r[0] for r in all_(con, "SELECT DISTINCT insurance FROM patients")}
    check(payers == {"Medicare", "SampleCommercial"}, f"payers in data: {sorted(payers)}",
          "expected only Medicare and SampleCommercial (no Aetna etc.)")
    lo, hi = one(con, "SELECT MIN(age), MAX(age) FROM patients")
    check(lo >= 18 and hi <= 85, f"patient ages {lo}-{hi} (expected within 18-85)")
    check(one(con, "SELECT COUNT(*) - COUNT(DISTINCT claim_id) FROM claims")[0] == 0, "claim IDs are unique")
    john = one(con, "SELECT c.patient_id, c.procedure_code, c.conservative_treatment_weeks, c.red_flag_present, "
                    "p.insurance, p.state FROM claims c JOIN patients p ON p.patient_id = c.patient_id "
                    "WHERE c.claim_id = 'C10001'")
    ok = bool(john) and john[0] == "P1000" and int(john[1]) == 72149 and int(john[2]) == 3 \
        and not john[3] and john[4] == "SampleCommercial" and john[5] == "CA"
    check(ok, "John = C10001: P1000, SampleCommercial, CA, 72149, 3 weeks, no red flag", f"found {john}")


# -------------------------------------------------------- Yashasvi: policy
def check_policy(con):
    head("YASHASVI - retrieve_policy()")
    try:
        from retrieve_policy import retrieve_policy
    except Exception as e:  # noqa: BLE001
        rep("FAIL", "cannot import retrieve_policy", str(e)[:100])
        return None
    keys = {"found", "procedure_code", "payer", "state", "patient_region", "jurisdiction",
            "policy_id", "synthetic", "sections", "message"}
    a = retrieve_policy("72148", "Medicare", "MA")
    check(keys <= set(a), "output has every field of the agreed format")
    check(a["found"] and a["policy_id"] == "medicare_lcd_lumbar_mri" and a["jurisdiction"] == "JK"
          and a["synthetic"] is True, "72148 / Medicare / MA -> Medicare LCD, region JK, synthetic")
    check(len(a["sections"]) == 4 and all(s["chunk_id"].startswith("medicare_lcd_lumbar_mri::") for s in a["sections"]),
          "Medicare policy returns 4 sections with chunk IDs")
    b = retrieve_policy("72148", "SampleCommercial", "TX")
    check(b["found"] and b["policy_id"] == "commercial_lumbar_mri" and b["jurisdiction"] == "national",
          "72148 / SampleCommercial / TX -> commercial lumbar MRI, national")
    c = retrieve_policy("72148", "Medicare", "CA")
    check(c["found"] is False and c["sections"] == [] and "human review" in c["message"].lower(),
          "72148 / Medicare / CA -> not found, message says route to human review")
    d = retrieve_policy("72149", "SampleCommercial", "CA")
    check(d["found"] and d["policy_id"] == "commercial_lumbar_mri", "72149 / SampleCommercial / CA (John) -> commercial policy")
    rows = all_(con, "SELECT c.procedure_code, p.insurance, p.state FROM claims c "
                     "JOIN patients p ON p.patient_id = c.patient_id "
                     "WHERE c.procedure_code IN (72148, 72149, 72158)")
    hit = sum(1 for code, payer, st in rows if retrieve_policy(str(code), payer, st)["found"])
    check(len(rows) == 199 and hit == 199, f"lumbar MRI claims that find a policy: {hit}/{len(rows)} (demo says 199/199)")
    return retrieve_policy


# ---------------------------------------------------------- Rekha: evaluate
def check_agent(con):
    head("REKHA - evaluate_claim() on the four plan test cases")
    try:
        import evaluate_claim as ev
    except Exception as e:  # noqa: BLE001
        rep("FAIL", "cannot import evaluate_claim", str(e)[:100])
        return

    def rule(r, rid):
        return next((x for x in r["rules"] if x["rule_id"] == rid), None)

    j = ev.evaluate_claim("C10001", con=con)
    check(j["decision"] == "DOES_NOT_MEET_CRITERIA" and j["routing"] == "human_review"
          and rule(j, "r1_conservative_or_red_flag")["result"] == "FAIL",
          "John C10001 -> DOES_NOT_MEET_CRITERIA, Rule 1 FAIL, human_review")
    check(j["policy"]["policy_id"] == "commercial_lumbar_mri" and len(j["rules"]) == 2,
          "John uses the commercial policy and only 2 rules (radiculopathy rule is Medicare-only)")
    r = ev.evaluate_claim("C10286", con=con)
    x = rule(r, "r1_conservative_or_red_flag")
    check(x["result"] == "PASS" and x["via"] == "red_flag_exception" and r["decision"] == "MEETS_CRITERIA",
          "Red flag C10286 -> Rule 1 PASS via red-flag exception, MEETS_CRITERIA")
    c = ev.evaluate_claim("C10006", con=con)
    check(c["policy"]["policy_id"] == "commercial_lumbar_mri" and c["decision"] == "MEETS_CRITERIA",
          "Commercial C10006 -> commercial policy, MEETS_CRITERIA")
    m = ev.evaluate_claim("C10203", con=con)
    check(m["policy"]["jurisdiction"] == "JK" and rule(m, "r1_conservative_or_red_flag")["result"] == "FAIL"
          and rule(m, "r2_radiculopathy_dx_or_red_flag")["result"] == "PASS",
          "Medicare C10203 -> LCD region JK, Rule 1 FAIL, Rule 2 PASS")
    n = ev.evaluate_claim("C10000", con=con)
    check(n["policy"]["found"] is False and n["routing"] == "human_review" and n["rules"] == [],
          "No policy (office visit C10000) -> routed to human, no rules run")
    for res in (j, r, c, m, n):
        check(set(res["admin"]) >= {"billing_code", "auth_duration", "follow_up_plan"}
              and res["admin"]["auth_duration"]["basis"] == "team_assumption"
              and res["admin"]["follow_up_plan"]["basis"] == "team_assumption",
              f"{res['claim_id']}: admin elements present and labeled team_assumption")


# --------------------------------------------------- wiring, wording, files
FILES = ["app.py", "setup_duckdb.py", "add_procedures.py", "src/agent/evaluate_claim.py",
         "src/rag/retrieve_policy.py", "src/ui/data_panel.py", "app_panels/policy_panel.py",
         "app_panels/agent_panel.py", "config/criteria_rules.yaml", "test_evaluate_claim.py"]


def top_level_names(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def check_static():
    head("APP WIRING, WORDING AND FILES")
    for f in FILES:
        check((ROOT / f).exists(), f"file exists: {f}", "missing -- copy it into the repo")
    for f in [p for p in ROOT.rglob("*.py") if ".venv" not in p.parts and "site-packages" not in p.parts]:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            rep("FAIL", f"syntax error in {f.relative_to(ROOT)}", str(e)[:80])
    rep("PASS", "every .py file compiles")

    app = (ROOT / "app.py").read_text(encoding="utf-8")
    # every name app.py imports from our own modules must really exist
    for node in ast.walk(ast.parse(app)):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in ("src", "app_panels"):
            path = ROOT / (node.module.replace(".", "/") + ".py")
            have = top_level_names(path) if path.exists() else set()
            missing = [a.name for a in node.names if a.name not in have]
            check(path.exists() and not missing, f"app.py import ok: from {node.module} import {', '.join(a.name for a in node.names)}",
                  f"missing {missing or path}")
    check("render_agent_panel(" in app, "app.py calls render_agent_panel (your panel is wired in)",
          "app.py is still the old version -- copy the new app.py")
    side = app[app.find("SIDEBAR"):app.find("MAIN CONTENT")]
    check("How It Works" not in side and "GitHub" not in side, "sidebar has no 'How It Works' / GitHub / demo date")
    check(all(n in side for n in ("Nancy", "Yashasvi", "Rekha")), "sidebar lists the three team members")

    banned = ["auto-approve", "auto_approve", "automatically approved", "medical director"]
    for f in ["app.py", "app_panels/agent_panel.py", "app_panels/policy_panel.py", "src/agent/evaluate_claim.py",
              "src/ui/data_panel.py"]:
        text = (ROOT / f).read_text(encoding="utf-8").lower()
        bad = [w for w in banned if w in text]
        check(not bad, f"no forbidden wording in {f}", f"found {bad}")
    check("### 📋 decision" not in app.lower() and "evaluation & decision" not in app.lower(),
          "app.py has no 'Decision' headings (should say Assessment)")
    check("only the insurer approves or denies" in app, "app.py footer says only the insurer approves or denies")
    for f in ["README.md", "data/DATA_STRUCTURE.txt", "snowflake_schema.md", "app.py"]:
        p = ROOT / f
        if p.exists():
            check("aetna" not in p.read_text(encoding="utf-8").lower(), f"no 'Aetna' in {f}")
    rd = (ROOT / "README.md").read_text(encoding="utf-8")
    if "streamlit run app.py" in rd:
        rep("PASS", "README explains how to run the app")
    else:
        rep("WARN", "README has no 'how to run the app' section", "Nancy's plan item: pip install -> setup_duckdb -> streamlit run app.py")
    for f in ("setup_duckdb.py", "add_procedures.py"):
        if (ROOT / f).exists():
            if "OR REPLACE" in (ROOT / f).read_text(encoding="utf-8").upper():
                rep("PASS", f"{f} can be re-run safely")
            else:
                rep("WARN", f"{f} uses plain CREATE TABLE", "second run will fail with 'table already exists'")
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    check("streamlit" in req and "duckdb" in req, "requirements.txt lists streamlit and duckdb")

    # filter_claims needs no database, so it can be tested without streamlit if it imports
    try:
        import streamlit  # noqa: F401
        from src.ui.data_panel import filter_claims
        labels = ["a", "b", "c"]
        rows = [("C1", "P1", 72148, "Medicare", "NY"), ("C2", "P2", 72148, "SampleCommercial", "CA"),
                ("C3", "P3", 99214, "Medicare", "CA")]
        check(filter_claims(labels, rows, "medicare 72148")[0] == ["a"] and filter_claims(labels, rows, "ca")[0] == ["b", "c"],
              "claim search works ('medicare 72148', and 'ca' does not match Medicare)")
    except ImportError:
        rep("SKIP", "claim search unit check", "streamlit is not installed here")
    except Exception as e:  # noqa: BLE001
        rep("FAIL", "claim search (src/ui/data_panel.py filter_claims)", str(e)[:90])


# -------------------------------------------------------- run other tools
def run_tools():
    head("YOUR TEST SUITE AND THE CITATION CHECKER (run as separate programs)")
    for label, cmd, ok_text in [
        ("test_evaluate_claim.py", [sys.executable, "test_evaluate_claim.py"], "ALL CHECKS PASSED"),
        ("verify-citations", [sys.executable, "src/rag/rag_pipeline.py", "verify-citations"], "0 missing"),
    ]:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            out = p.stdout + p.stderr
            check(p.returncode == 0 and ok_text in out, f"{label} -> '{ok_text}'",
                  "see output: " + out.strip().splitlines()[-1][:100] if out.strip() else "no output")
        except Exception as e:  # noqa: BLE001
            rep("FAIL", label, str(e)[:90])


def main():
    con, kind = open_db()
    print(f"(database: {kind})")
    check_data(con, kind)
    check_policy(con)
    check_agent(con)
    con.close()                      # release the DuckDB file before the next programs open it
    check_static()
    run_tools()
    print("\n" + "=" * 60)
    print(f"PASS {COUNT['PASS']}   FAIL {COUNT['FAIL']}   WARN {COUNT['WARN']}   SKIP {COUNT['SKIP']}")
    print("ALL GOOD" if COUNT["FAIL"] == 0 else "SOMETHING NEEDS FIXING -- see the [FAIL] lines above")
    print("""
Now check on screen (python3 -m streamlit run app.py):
  1. Data tab: type 'medicare ny' in the search box; the list narrows.
  2. C10001 -> Evaluate -> DOES_NOT_MEET_CRITERIA; Summary says commercial_lumbar_mri / SampleCommercial.
  3. Pick C10203 (do NOT click Evaluate): Assessment tab asks you to click Evaluate (no stale result).
  4. Evaluate C10203: Summary now says medicare_lcd_lumbar_mri / JK.
  5. C10286 -> Evaluate: Rule 1 shows PASS (red-flag exception).  C10000 -> 'No policy' / cannot assess.
  6. Sidebar: team names only. No 'auto-approve' or 'Decision' anywhere.""")
    sys.exit(1 if COUNT["FAIL"] else 0)


if __name__ == "__main__":
    main()
