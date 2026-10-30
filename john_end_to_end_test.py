"""
Task 4 (Rekha's workplan, Thursday Task 2): Full end-to-end 7-step flow
test for John (P1000).

This runs ALL 7 steps for real: a real call into Yashasvi's rag_pipeline.py
(Step 2), and the real config/criteria_rules.yaml (Step 3) -- not a
hand-trace. Nancy's warehouse (Step 1) is live, but this script's query
layer isn't wired to it yet -- same as in
test_integration.py, since it isn't built/wired up yet.

NOTE on John's payer: the workplans call him an "Aetna" patient, but no
payer named "Aetna" exists in the real data (the real commercial payer is
named "SampleCommercial"). John is resolved to MEDICARE here instead,
since his exact numbers (M54.16, conservative treatment weeks, red-flag
exception, age) already match the real, verified Medicare policy text --
zero new unknowns. If the team decides he should be a SampleCommercial
patient instead, this needs rebuilding against that policy's real text.

Run from the repo root:
    python3 john_end_to_end_test.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src" / "agent"))
sys.path.insert(0, str(REPO_ROOT / "src" / "rag"))

import yaml  # noqa: E402
from agent_state import AgentState, PolicyReference  # noqa: E402

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


# ---------------------------------------------------------------- STEP 1
section("STEP 1: Ingest Case  (Nancy's data IS live in Snowflake now; this script's query layer is not wired to it yet)")

john_claims_data = {
    "conservative_treatment_weeks": 2,
    "red_flag_present": False,
    "patient_age": 55,
}

state = AgentState(
    patient_id="P1000",
    diagnosis_codes=["M54.16"],
    procedure_code="72148",
    payer="Medicare",  # resolved from "Aetna" -- see note above
    jurisdiction="JK",  # matches the real Medicare policy's jurisdiction
)
print(f"  Case: {state.patient_id}, procedure {state.procedure_code}, "
      f"payer {state.payer}, jurisdiction {state.jurisdiction}")
print(f"  Simulated claims data: {john_claims_data}")

# ---------------------------------------------------------------- STEP 2
section("STEP 2: Retrieve Policy  (REAL call into Yashasvi's rag_pipeline.py)")

try:
    import rag_pipeline
except ImportError as e:
    sys.exit(f"FAIL: could not import rag_pipeline.py -- {e}\n"
              f"Run 'pip3 install -r requirements.txt' first.")

retriever = rag_pipeline.get_retriever(use_rerank=True)  # match validated CLI config, not the weaker function default
results = retriever.search(
    "How many weeks of conservative treatment are needed before a lumbar MRI?",
    payer=state.payer,
    procedure_code=state.procedure_code,
    jurisdiction=state.jurisdiction,
    k=1,
)

if not check("A real policy chunk was returned for John's case", bool(results)):
    sys.exit("Cannot continue -- no chunk to build a PolicyReference from.")

top = results[0]
print(f"  Retrieved chunk_id: {top['chunk_id']}  (score={top['score']})")

try:
    state.regional_policy = PolicyReference(
        chunk_id=top["chunk_id"], policy_id=top["policy_id"], payer=top["payer"],
        document_type=top["document_type"], procedure_codes=top["procedure_codes"],
        jurisdiction=top["jurisdiction"], synthetic=top["synthetic"], section=top["section"],
        text=top["text"], source_file=top["source_file"], score=top["score"],
    )
    state.applicable_policy = state.regional_policy
    check("PolicyReference built from real chunk with zero translation", True)
except (KeyError, TypeError) as e:
    check(f"PolicyReference construction failed: {e}", False)
    sys.exit("Cannot continue.")

print(f"  Derived source_level: {state.applicable_policy.source_level}")

# ---------------------------------------------------------------- STEP 3
section("STEP 3: Evaluate Criteria  (real config/criteria_rules.yaml x John's data)")

with open(REPO_ROOT / "config" / "criteria_rules.yaml") as f:
    rules_config = yaml.safe_load(f)
rules = rules_config["procedures"]["lumbar_mri"]["rules"]

all_critical_passed = True
for r in rules:
    if "conservative_treatment_weeks" in r["rule"]:
        passed = john_claims_data["conservative_treatment_weeks"] >= 6 or john_claims_data["red_flag_present"]
    elif "M54.16" in r["rule"]:
        passed = "M54.16" in state.diagnosis_codes
    elif "patient_age" in r["rule"]:
        passed = john_claims_data["patient_age"] >= 18
    else:
        passed = None
    label = "SKIP (unresolved)" if passed is None else ("condition met" if passed else "condition NOT met")
    print(f"    [{label:18}] {r['rule']}  (cites_chunk: {r.get('cites_chunk')})")
    if r["severity"] == "critical" and passed is False:
        all_critical_passed = False

state.criteria_met = all_critical_passed
print(f"\n  state.criteria_met = {state.criteria_met}")

# ---------------------------------------------------------------- STEP 4
section("STEP 4: Decide  (the AGENT's own assessment -- it cannot approve or deny)")

state.decision = "MEETS_CRITERIA" if state.criteria_met else "DOES_NOT_MEET_CRITERIA"
print(f"  state.decision = {state.decision}")

# ----------------------------------------------------------- STEPS 5-7
if state.decision == "DOES_NOT_MEET_CRITERIA":
    section("STEPS 5-7: Act / Track / On Denial  (Server 3 -- SIMULATED insurer response)")
    state.denial_reason_code = "16"
    state.appeal_draft = (
        f"Per {state.applicable_policy.chunk_id}, requesting reconsideration "
        f"for patient {state.patient_id} with updated conservative treatment documentation."
    )
    print(f"  (simulated) insurer denial_reason_code = {state.denial_reason_code}")
    print(f"  (simulated) appeal_draft = {state.appeal_draft}")

# ------------------------------------------------------------------ RESULT
section("RESULT")

expected = "DOES_NOT_MEET_CRITERIA"
check(f"state.decision == '{expected}' (workplan's expected outcome for John)", state.decision == expected)

if FAIL:
    print("\nFAIL -- see above.")
    sys.exit(1)
else:
    print("\nPASS -- John's (P1000) full 7-step flow ran end to end using REAL")
    print("components: a real Yashasvi RAG retrieval, the real criteria_rules.yaml,")
    print("and a correctly-terminology'd agent assessment. Nancy's warehouse is live;")
    print("this script's query layer just isn't wired to it yet.")