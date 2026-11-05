"""
retrieve_policy() - policy lookup for the agent and the demo app (owner: Yashasvi)

Wraps the real search pipeline in rag_pipeline.py (FAISS + reranker).

    from retrieve_policy import retrieve_policy
    policy = retrieve_policy("72148", "Medicare", "MA")                    # main sections
    policy = retrieve_policy("72148", "Medicare", "MA", "documents needed") # search

Command line (for testing):
    python src/rag/retrieve_policy.py 72148 Medicare MA
    python src/rag/retrieve_policy.py 72148 Medicare MA "how many weeks of therapy?"
    python src/rag/retrieve_policy.py 72148 Medicare CA --save analysis/retrieve_policy_no_policy.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the app can import this file
from rag_pipeline import build_chunks, get_retriever, jurisdiction_for_state, load_config  # noqa: E402

# Sections returned when no question is asked, in this order (whichever the policy has).
MAIN_SECTIONS = [
    "coverage_indications_limitations_and_or_medical_necessity",  # Medicare LCD
    "medical_necessity_criteria",                                 # commercial
    "red_flag_conditions",
    "limitations",
    "not_medically_necessary",
    "precertification_requirements",
    "documentation_requirements",
]

_retriever = None   # search models are loaded once and reused
_chunks = None


def warm_up():
    """Load the search models now (call once at app start-up)."""
    global _retriever
    if _retriever is None:
        _retriever = get_retriever(quiet=True)
    return _retriever


def _all_chunks():
    global _chunks
    if _chunks is None:
        _chunks = build_chunks(load_config(), warn=False)
    return _chunks


def _find_policy(procedure_code, payer, jurisdiction):
    """The policy that applies: same payer, covers the code, and is national or
    matches the patient's region. A regional policy is preferred over a national one."""
    matches = []
    for p in load_config()["policies"]:
        codes = [str(c) for c in (p.get("procedure_codes") or [p["procedure_code"]])]
        region = str(p.get("jurisdiction", "national"))
        if (p["payer"].lower() == payer.lower() and str(procedure_code) in codes
                and region in ("national", jurisdiction)):
            matches.append(p)
    matches.sort(key=lambda p: p.get("jurisdiction", "national") == "national")
    return matches[0] if matches else None


def _section(chunk, score=None):
    return {"chunk_id": chunk["chunk_id"], "section": chunk["section"],
            "text": chunk["text"], "score": score}


def retrieve_policy(procedure_code, payer, state, question=None):
    """Return the policy sections that apply to a claim. See the team plan, section A3."""
    procedure_code, payer = str(procedure_code).strip(), str(payer).strip()
    state = (state or "").strip().upper()
    jurisdiction = jurisdiction_for_state(state) if state else None
    result = {"found": False, "procedure_code": procedure_code, "payer": payer,
              "state": state, "patient_region": jurisdiction,
              "jurisdiction": jurisdiction, "policy_id": None,
              "synthetic": None, "sections": [], "message": ""}

    policy = _find_policy(procedure_code, payer, jurisdiction)
    if policy is None:
        where = f" in region {jurisdiction}" if (payer.lower() == "medicare" and jurisdiction) else ""
        result["message"] = (f"No {payer} policy for procedure {procedure_code}{where}. "
                             f"Route to human review.")
        return result

    # jurisdiction = where the POLICY applies ("JK" or "national");
    # patient_region = the patient's Medicare region from their state.
    result.update(found=True, policy_id=policy["policy_id"],
                  synthetic=bool(policy.get("synthetic", False)),
                  jurisdiction=str(policy.get("jurisdiction", "national")))

    if question:
        # Full search: FAISS + reranker, filtered to this payer, code and region.
        hits = warm_up().search(question, payer, procedure_code, jurisdiction, k=3)
        result["sections"] = [_section(h, h["score"]) for h in hits]
        result["message"] = f"Top {len(hits)} sections for: {question}"
    else:
        # No question: return the policy's main sections directly by chunk ID.
        own = {c["chunk_id"].split("::", 1)[1]: c for c in _all_chunks()
               if c["policy_id"] == policy["policy_id"]}
        result["sections"] = [_section(own[s]) for s in MAIN_SECTIONS if s in own]
        result["message"] = "Main policy sections (direct lookup by chunk ID, no search score)."
    return result


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--save"]
    save = None
    if "--save" in sys.argv:
        i = sys.argv.index("--save")
        save = sys.argv[i + 1]
        args.remove(save)
    if len(args) < 3:
        sys.exit('usage: python src/rag/retrieve_policy.py CODE PAYER STATE ["question"] [--save file.json]')
    out = retrieve_policy(args[0], args[1], args[2], args[3] if len(args) > 3 else None)
    text = json.dumps(out, indent=2)
    print(text)
    if save:
        Path(save).parent.mkdir(parents=True, exist_ok=True)
        Path(save).write_text(text, encoding="utf-8")
        print(f"\nSaved to {save}")
