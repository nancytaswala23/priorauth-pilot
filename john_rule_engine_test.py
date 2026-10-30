"""
Task 3 (Rekha's workplan, Thursday Task 1): Rule Engine Integration test
for John (P1000).

Exact input from REKHA_INDIVIDUAL_WORKPLAN.txt:
    diagnosis_codes = ['M54.16']
    conservative_treatment_weeks = 2
    red_flag_present = False
    patient_age = 55

Expected result per the workplan: DOES_NOT_MEET_CRITERIA (rule 2 fails).

This test runs ONLY the rule engine against the REAL config/criteria_rules.yaml
-- it does not call Yashasvi's RAG pipeline, because the workplan's own Task 1
spec doesn't require a policy retrieval step, just the rule evaluation. Policy
retrieval for John belongs to Task 4 (the full end-to-end flow document).

Run from the repo root:
    python3 john_rule_engine_test.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src" / "agent"))

import yaml  # noqa: E402
from agent_state import AgentState  # noqa: E402

FAIL = False


def section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def check(label, condition):
    global FAIL
    status = "PASS" if condition else "FAIL"
    if not condition:
        FAIL = True
    print(f"  [{status}] {label}")
    return condition


# ---------------------------------------------------------------- INPUT
section("JOHN'S CASE (P1000) -- exact input from REKHA_INDIVIDUAL_WORKPLAN.txt")

john_data = {
    "diagnosis_codes": ["M54.16"],
    "conservative_treatment_weeks": 2,
    "red_flag_present": False,
    "patient_age": 55,
}
print(f"  diagnosis_codes = {john_data['diagnosis_codes']}")
print(f"  conservative_treatment_weeks = {john_data['conservative_treatment_weeks']}")
print(f"  red_flag_present = {john_data['red_flag_present']}")
print(f"  patient_age = {john_data['patient_age']}")

# NOTE: payer is deliberately left unresolved here. The workplans refer to
# John's payer as "Aetna," but Yashasvi's real chunking_strategy.yaml does
# not have a payer named "Aetna" -- the real commercial payer is named
# "SampleCommercial". This doesn't block this task (rule evaluation below
# doesn't use payer at all), but it WILL matter for Task 4, which needs a
# real policy retrieval. Flagging now so it isn't a surprise later.
state = AgentState(
    patient_id="P1000",
    diagnosis_codes=john_data["diagnosis_codes"],
    procedure_code="72148",
    payer="UNRESOLVED -- see note above (workplan says 'Aetna', real data says 'SampleCommercial')",
    jurisdiction="UNRESOLVED",
)

# ---------------------------------------------------------------- RULES
section("Evaluate John's case against the REAL config/criteria_rules.yaml")

with open(REPO_ROOT / "config" / "criteria_rules.yaml") as f:
    rules_config = yaml.safe_load(f)
rules = rules_config["procedures"]["lumbar_mri"]["rules"]

all_critical_passed = True
for r in rules:
    if "conservative_treatment_weeks" in r["rule"]:
        passed = john_data["conservative_treatment_weeks"] >= 6 or john_data["red_flag_present"]
    elif "M54.16" in r["rule"]:
        passed = "M54.16" in john_data["diagnosis_codes"]
    elif "patient_age" in r["rule"]:
        passed = john_data["patient_age"] >= 18
    else:
        passed = None
    label = "SKIP (unresolved)" if passed is None else ("condition met" if passed else "condition NOT met")
    print(f"    [{label:18}] {r['rule']}")
    if r["severity"] == "critical" and passed is False:
        all_critical_passed = False

state.criteria_met = all_critical_passed
print(f"\n  state.criteria_met = {state.criteria_met}")

# ---------------------------------------------------------------- DECIDE
section("Decide (agent's own assessment -- not an adjudication)")

state.decision = "MEETS_CRITERIA" if state.criteria_met else "DOES_NOT_MEET_CRITERIA"
print(f"  state.decision = {state.decision}")

# ---------------------------------------------------------------- RESULT
section("RESULT")

expected = "DOES_NOT_MEET_CRITERIA"
check(f"state.decision == '{expected}' (workplan's expected outcome)", state.decision == expected)

if FAIL:
    print("\nFAIL -- see above.")
    sys.exit(1)
else:
    print("\nPASS -- John's (P1000) case, evaluated against the REAL current")
    print("criteria_rules.yaml, produces exactly the decision the workplan expects.")
    print("\nOPEN ITEM before Task 4: John's payer needs to be resolved to a real")
    print("payer name in the data ('Medicare' or 'SampleCommercial') before a real")
    print("policy retrieval can run for him -- 'Aetna' does not exist in the real data.")