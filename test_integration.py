"""
PriorAuthPilot -- integration test (owner: Rekha)

What this ACTUALLY proves:
  1. Yashasvi's real RAG pipeline (src/rag/rag_pipeline.py) returns a real
     policy chunk from the real synthetic policy files.
  2. That real chunk plugs directly into Rekha's PolicyReference with ZERO
     manual field translation -- the whole point of the schema fix.
  3. The retrieved chunk_id matches what criteria_rules.yaml already claims
     to cite for Rule 1 -- a real cross-check, not an assumption.
  4. Rekha's criteria_rules.yaml rules can be evaluated end to end into an
     actual decision on AgentState.

What this does NOT prove (and can't, without live Snowflake access):
  - Nancy's actual Snowflake schema / live data. The claims data below is a
    SIMULATED stand-in, shaped exactly like her real CLAIMS table columns.
    Replace `simulated_claims_lookup` with a real Server 1 call once that
    exists.

Run from the repo root:
    python3 test_integration.py
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
section("STEP 1: Ingest Case  (Nancy's Server 1 -- SIMULATED, no live Snowflake here)")

# Shaped exactly like Nancy's real CLAIMS table columns. In the real system,
# Server 1 would compute conservative_treatment_weeks from multiple CLAIMS
# rows over time (per get_conservative_treatment() in mcp_design.md) --
# here we just assert a plausible result for one test patient.
simulated_claims_lookup = {
    # diagnosis_codes includes M54.16 (lumbar radiculopathy) alongside the
    # presenting M54.5 (low back pain) -- plausible real-world pairing
    "P001": {"conservative_treatment_weeks": 4, "patient_age": 34, "diagnosis_codes": ["M54.5", "M54.16"]},
}

state = AgentState(
    patient_id="P001",
    diagnosis_codes=["M54.5"],
    procedure_code="72148",
    payer="Medicare",
    jurisdiction="JK",  # matches Yashasvi's real Medicare policy jurisdiction, not a guess
)
print(f"  Case: {state.patient_id}, procedure {state.procedure_code}, "
      f"payer {state.payer}, jurisdiction {state.jurisdiction}")

# ---------------------------------------------------------------- STEP 2
section("STEP 2: Retrieve Policy  (REAL call into Yashasvi's rag_pipeline.py)")

try:
    import rag_pipeline
except ImportError as e:
    sys.exit(f"FAIL: could not import rag_pipeline.py -- {e}\n"
              f"Run 'pip3 install -r requirements.txt' first.")

try:
    # IMPORTANT: get_retriever()'s own default is use_rerank=False, but
    # Yashasvi's CLI defaults --rerank to True, and her 7/8 (top-1) / 8/8
    # (top-3) eval numbers were produced WITH reranking on. Calling the bare
    # function without this flag silently uses the weaker, non-reranked
    # path -- which is exactly what produced the wrong chunk the first time
    # we ran this test. Match her actual validated configuration here.
    retriever = rag_pipeline.get_retriever(use_rerank=True)
except SystemExit as e:
    sys.exit(f"FAIL: rag_pipeline could not build its index -- {e}")

results = retriever.search(
    # exact wording from Yashasvi's own EVAL_SET -- not a paraphrase this time
    "How many weeks of conservative treatment are needed before a lumbar MRI?",
    payer=state.payer,
    procedure_code=state.procedure_code,
    jurisdiction=state.jurisdiction,
    k=1,
)

if not check("A real policy chunk was returned", bool(results)):
    sys.exit("Cannot continue -- no chunk to build a PolicyReference from.")

top = results[0]
print(f"  Retrieved chunk_id: {top['chunk_id']}  (score={top['score']})")

# The actual proof point: build PolicyReference straight from her real dict,
# field for field, no renaming or translation.
try:
    state.regional_policy = PolicyReference(
        chunk_id=top["chunk_id"],
        policy_id=top["policy_id"],
        payer=top["payer"],
        document_type=top["document_type"],
        procedure_codes=top["procedure_codes"],
        jurisdiction=top["jurisdiction"],
        synthetic=top["synthetic"],
        section=top["section"],
        text=top["text"],
        source_file=top["source_file"],
    )
    state.applicable_policy = state.regional_policy
    check("PolicyReference built from real chunk with zero translation", True)
except (KeyError, TypeError) as e:
    check(f"PolicyReference construction failed: {e}", False)
    sys.exit("Cannot continue.")

print(f"  Derived source_level: {state.applicable_policy.source_level}")

# ---------------------------------------------------------------- STEP 2b
section("STEP 2b: Cross-check against criteria_rules.yaml's existing citation")

with open(REPO_ROOT / "config" / "criteria_rules.yaml") as f:
    rules_config = yaml.safe_load(f)
rules = rules_config["procedures"]["lumbar_mri"]["rules"]

rule1_cites = rules[0]["cites_chunk"]
check(
    f"Retrieved chunk_id matches Rule 1's cites_chunk ('{rule1_cites}')",
    top["chunk_id"] == rule1_cites,
)

# ---------------------------------------------------------------- STEP 3
section("STEP 3: Evaluate Criteria  (criteria_rules.yaml x simulated CLAIMS/PATIENTS data)")

claims = simulated_claims_lookup[state.patient_id]
all_critical_passed = True

for r in rules:
    if "conservative_treatment_weeks" in r["rule"]:
        passed = claims["conservative_treatment_weeks"] >= 6
    elif "M54.16" in r["rule"]:
        passed = "M54.16" in claims["diagnosis_codes"]
    elif "patient_age" in r["rule"]:
        passed = claims["patient_age"] >= 18
    else:
        passed = None  # any future unresolved rule
    # NOTE: these are business-rule outcomes, not test assertions -- "not met"
    # means the simulated patient doesn't qualify, which can be the CORRECT
    # and expected result (e.g. we deliberately test a denial scenario here).
    label = "SKIP (unresolved)" if passed is None else ("condition met" if passed else "condition NOT met")
    print(f"    [{label:18}] {r['rule']}")
    if r["severity"] == "critical" and passed is False:
        all_critical_passed = False

state.criteria_met = all_critical_passed
print(f"\n  state.criteria_met = {state.criteria_met}")

# ---------------------------------------------------------------- STEP 4
section("STEP 4: Decide")

state.decision = "APPROVED" if state.criteria_met else "DENIED"
print(f"  state.decision = {state.decision}")

if state.decision == "DENIED":
    state.denial_reason_code = "16"
    state.appeal_draft = (
        f"Per {state.applicable_policy.chunk_id}, requesting reconsideration "
        f"with updated conservative treatment documentation."
    )
    print(f"  state.denial_reason_code = {state.denial_reason_code}")
    print(f"  state.appeal_draft = {state.appeal_draft}")

# ------------------------------------------------------------------ RESULT
section("RESULT")
if FAIL:
    print("FAIL -- see the FAIL lines above.")
    sys.exit(1)
else:
    print("PASS -- Yashasvi's real RAG output plugs directly into your")
    print("AgentState/PolicyReference with zero manual translation, and the")
    print("retrieved chunk matches what criteria_rules.yaml already claims.")
    print("Nancy's Server 1 was simulated here")
    print("that piece is actually built and wired up.")