"""
evaluate_claim() -- the agent's assessment of one claim (owner: Rekha)

    from evaluate_claim import evaluate_claim
    result = evaluate_claim("C10001")

The agent ASSESSES. It never approves or denies: only the insurer does.
Decisions: MEETS_CRITERIA | NEEDS_DOCS | DOES_NOT_MEET_CRITERIA

Flow (steps 1-4 of the 7-step loop):
    1. read the claim + patient from DuckDB, collect the patient's diagnosis history
    2. retrieve_policy(procedure, payer, state)            (Yashasvi)
    3. run the rules in config/criteria_rules.yaml that apply to this payer
    4. decide + route

The rule logic (evaluate_case) is a pure function with no database or search
dependency, so it can be tested on its own.
"""

import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = REPO_ROOT / "config" / "criteria_rules.yaml"
DB_PATH = Path(os.environ.get("PRIORAUTH_DB", REPO_ROOT / "priorauth.duckdb"))

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
MEETS, NEEDS_DOCS, DOES_NOT_MEET = "MEETS_CRITERIA", "NEEDS_DOCS", "DOES_NOT_MEET_CRITERIA"

# Routing values (Step 5 vocabulary). There is deliberately no "auto approve":
# the agent can only recommend submitting; the insurer decides.
READY_TO_SUBMIT, REQUEST_DOCS, HUMAN_REVIEW = "ready_to_submit", "request_documentation", "human_review"

# TEAM DECISION NEEDED: the project allows only three decision values, and there is
# no value for "no policy / no rules, cannot assess". We use NEEDS_DOCS + human_review
# with an explicit reason. Change this one constant if the team adds a fourth value.
CANNOT_ASSESS_DECISION = NEEDS_DOCS

RADICULOPATHY_CODES = ["M54.16", "M54.17", "M51.16"]


# ----------------------------------------------------------------- helpers

def _load_rules():
    with open(RULES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _to_bool(v):
    """The CSV/DuckDB column may arrive as bool, 0/1 or 'TRUE'/'FALSE'."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        return True if s in ("true", "t", "1", "yes") else False if s in ("false", "f", "0", "no") else None
    return bool(v)


def _yn(v):
    return "unknown" if v is None else ("yes" if v else "no")


def _import_retrieve_policy():
    sys.path.insert(0, str(REPO_ROOT / "src" / "rag"))
    from retrieve_policy import retrieve_policy  # noqa: E402
    return retrieve_policy


# ----------------------------------------------------- the three rule checks
# Each returns (result, via, observed_text). `via` is set when a rule passes only
# because of the red-flag exception.

def _r1_conservative_or_red_flag(c):
    w, rf = c.get("conservative_treatment_weeks"), c.get("red_flag_present")
    seen = f"{'unknown' if w is None else w} weeks of conservative treatment; red flag: {_yn(rf)}"
    if rf is True:
        return PASS, ("red_flag_exception" if (w is None or w < 6) else None), seen
    if w is not None and w >= 6:
        return PASS, None, seen
    if w is None or rf is None:
        return UNKNOWN, None, seen
    return FAIL, None, seen


def _r2_radiculopathy_or_red_flag(c):
    codes, rf = c.get("diagnosis_codes") or [], c.get("red_flag_present")
    seen = f"diagnosis history: {', '.join(codes) if codes else 'none'}; red flag: {_yn(rf)}"
    has_dx = any(code in codes for code in RADICULOPATHY_CODES)
    if has_dx:
        return PASS, None, seen
    if rf is True:
        return PASS, "red_flag_exception", seen
    if rf is None or not codes:
        return UNKNOWN, None, seen
    return FAIL, None, seen


def _r3_adult(c):
    age = c.get("patient_age")
    seen = f"age {age if age is not None else 'unknown'}"
    if age is None:
        return UNKNOWN, None, seen
    return (PASS if age >= 18 else FAIL), None, seen


RULE_CHECKS = {
    "r1_conservative_or_red_flag": _r1_conservative_or_red_flag,
    "r2_radiculopathy_dx_or_red_flag": _r2_radiculopathy_or_red_flag,
    "r3_adult_age": _r3_adult,
}

FAIL_TEXT = {
    "r1_conservative_or_red_flag": lambda c: (
        f"{c['conservative_treatment_weeks']} weeks of conservative treatment (policy needs 6 or more) "
        f"and no red flag"),
    "r2_radiculopathy_dx_or_red_flag": lambda c: (
        "no radiculopathy diagnosis (M54.16, M54.17 or M51.16) in the patient's history and no red flag"),
    "r3_adult_age": lambda c: f"patient is {c['patient_age']}, under the team's age-18 scope assumption",
}


# ------------------------------------------------------------ pure rule engine

def evaluate_case(case, policy, rules_cfg=None):
    """Apply the rules to one case. `case` needs: claim_id, patient_id, procedure_code,
    payer, state, patient_age, diagnosis_codes, conservative_treatment_weeks,
    red_flag_present. `policy` is retrieve_policy()'s output. Returns the full result dict."""
    rules_cfg = rules_cfg or _load_rules()
    code, payer = str(case["procedure_code"]), str(case["payer"])
    cites_key = f"{payer.lower()}_cites_chunk"

    result = {
        "claim_id": case["claim_id"], "patient_id": case["patient_id"],
        "procedure_code": code, "payer": payer, "state": case.get("state"),
        "inputs": {k: case.get(k) for k in ("patient_age", "diagnosis_codes",
                                            "conservative_treatment_weeks", "red_flag_present")},
        "rules": [], "not_evaluated": [], "warnings": [],
        "decision": None, "decision_reason": "", "routing": None,
        "admin": {}, "policy": policy,
    }

    # Which rule family covers this procedure?
    family = next((f for f in rules_cfg["procedures"].values()
                   if code in [str(x) for x in f.get("procedure_codes", [])]), None)

    # No policy, or no rules for this procedure -> cannot assess -> a human decides.
    # (An empty result is NEVER read as "no requirements".)
    if not policy.get("found") or family is None:
        why = (policy.get("message") or "No policy found.") if not policy.get("found") else (
            f"No rules are defined for procedure {code}.")
        why = why.replace(" Route to human review.", "").strip()   # we add our own routing sentence below
        result.update(
            decision=CANNOT_ASSESS_DECISION, routing=HUMAN_REVIEW,
            decision_reason=f"Cannot assess this claim: {why} Routed to a human. "
                            f"This does not mean the procedure has no requirements.")
        result["admin"] = _admin(code, HUMAN_REVIEW, policy)
        return result

    section_ids = {s["chunk_id"] for s in policy.get("sections", [])}

    for r in family["rules"]:
        if payer not in r.get("applies_to", [payer]):
            continue                                   # rule is scoped to another payer
        res, via, seen = RULE_CHECKS[r["id"]](case)
        cites = list(r.get(cites_key) or (r.get("cites_chunk") or []))
        missing = [c for c in cites if c not in section_ids]
        if missing:
            result["warnings"].append(f"Rule '{r['id']}' cites chunk(s) not in the retrieved policy: {missing}")
        result["rules"].append({
            "rule_id": r["id"], "rule": r["rule"], "basis": r["basis"], "result": res,
            "via": via, "observed": seen, "cites_chunk": cites, "citations_in_policy": not missing,
        })

    for item in family.get(f"{payer.lower()}_not_evaluated", []):
        result["not_evaluated"].append({"item": item, "basis": "team_assumption"})
    if code != "72148" and family.get("procedure_code_assumption"):
        result["not_evaluated"].append({"item": family["procedure_code_assumption"], "basis": "team_assumption"})

    _decide(result, case)
    result["admin"] = _admin(code, result["routing"], policy)
    return result


def _decide(result, case):
    rules = result["rules"]
    policy_fail = [r for r in rules if r["result"] == FAIL and r["basis"] != "team_assumption"]
    assume_fail = [r for r in rules if r["result"] == FAIL and r["basis"] == "team_assumption"]
    unknown = [r for r in rules if r["result"] == UNKNOWN]
    pass_n = sum(r["result"] == PASS for r in rules)

    if policy_fail:
        reasons = [f"Rule {i}: {FAIL_TEXT[r['rule_id']](case)}"
                   for i, r in enumerate(rules, 1) if r in policy_fail]
        decision, routing = DOES_NOT_MEET, HUMAN_REVIEW
        text = "Does not meet the policy criteria. " + "; ".join(reasons) + "."
        if result["not_evaluated"] and result["payer"] == "SampleCommercial":
            text += " Not checked (no data): pre-operative planning, a separate pathway in this policy."
    elif unknown:
        missing = ", ".join(r["observed"] for r in unknown)
        decision, routing = NEEDS_DOCS, REQUEST_DOCS
        text = f"Cannot finish the assessment: missing information ({missing})."
    elif assume_fail:
        decision, routing = NEEDS_DOCS, HUMAN_REVIEW
        text = (f"No policy criterion failed, but a team-assumption rule did: "
                f"{FAIL_TEXT[assume_fail[0]['rule_id']](case)}. Routed to a human instead of "
                f"reporting a policy failure.")
    else:
        decision, routing = MEETS, READY_TO_SUBMIT
        exc = [f"Rule {i}" for i, r in enumerate(rules, 1) if r["via"] == "red_flag_exception"]
        text = f"Meets the criteria that can be checked ({pass_n} of {len(rules)} rules passed"
        text += f"; {' and '.join(exc)} via the red-flag exception)." if exc else ")."
        if result["not_evaluated"]:
            text += " Some policy items could not be checked with our data (listed below)."
    result.update(decision=decision, routing=routing, decision_reason=text)


FOLLOW_UP = {
    READY_TO_SUBMIT: "Submit the request with the documents listed in the policy, then track status.",
    REQUEST_DOCS: "Ask the provider for the missing information, then re-run the assessment.",
    HUMAN_REVIEW: "A reviewer examines the failed or unassessable criteria before anything is submitted.",
}


def _admin(code, routing, policy):
    doc = next((s["chunk_id"] for s in policy.get("sections", [])
                if s["chunk_id"].endswith("::documentation_requirements")), None)
    return {
        "billing_code": code,
        "auth_duration": {"value": "Set by the insurer; not defined in our policies", "basis": "team_assumption"},
        "follow_up_plan": {"value": FOLLOW_UP[routing], "basis": "team_assumption"},
        "documentation_chunk": doc,   # fetched directly by chunk id, not by search
    }


# ------------------------------------------------------------------ data access

def load_case(claim_id, con):
    """Read one claim + its patient from DuckDB (tables `claims`, `patients`, as built by
    setup_duckdb.py). Collects diagnosis codes from the patient's claims dated on or before
    this claim's date_of_service. Returns None if the claim does not exist."""
    row = con.execute(
        "SELECT c.claim_id, c.patient_id, c.procedure_code, c.diagnosis_code, c.date_of_service, "
        "c.conservative_treatment_weeks, c.red_flag_present, p.age, p.state, p.insurance "
        "FROM claims c JOIN patients p ON p.patient_id = c.patient_id WHERE c.claim_id = ?",
        [claim_id]).fetchone()
    if row is None:
        return None
    cid, pid, proc, dx, dos, weeks, rf, age, state, payer = row
    hist = con.execute(
        "SELECT DISTINCT diagnosis_code FROM claims WHERE patient_id = ? AND date_of_service <= ? "
        "ORDER BY diagnosis_code", [pid, dos]).fetchall()
    codes = [h[0] for h in hist if h[0]] or ([dx] if dx else [])
    return {"claim_id": cid, "patient_id": pid, "procedure_code": str(proc), "payer": payer,
            "state": state, "patient_age": age, "diagnosis_codes": codes,
            "conservative_treatment_weeks": None if weeks is None else int(weeks),
            "red_flag_present": _to_bool(rf)}


def evaluate_claim(claim_id, con=None):
    """Assess one claim. Pass `con` (an open DuckDB connection) to reuse one; otherwise the
    demo database at PRIORAUTH_DB (default: <repo>/priorauth.duckdb) is opened with the
    default config, the same as the app, to avoid DuckDB's config-mismatch error."""
    opened = None
    if con is None:
        import duckdb
        con = opened = duckdb.connect(str(DB_PATH))
    try:
        case = load_case(claim_id, con)
    finally:
        if opened is not None:
            opened.close()
    if case is None:
        return {"claim_id": claim_id, "decision": CANNOT_ASSESS_DECISION, "routing": HUMAN_REVIEW,
                "decision_reason": f"Claim {claim_id} was not found in the database.",
                "rules": [], "not_evaluated": [], "warnings": [], "admin": {}, "policy": {"found": False}}
    policy = _import_retrieve_policy()(case["procedure_code"], case["payer"], case["state"])
    return evaluate_case(case, policy)


if __name__ == "__main__":
    import json
    print(json.dumps(evaluate_claim(sys.argv[1] if len(sys.argv) > 1 else "C10001"), indent=2, default=str))
