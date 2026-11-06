"""Agent panel for the Streamlit demo app (owner: Rekha).

Shows the output of evaluate_claim(). Called from app.py:

    from src.agent.evaluate_claim import evaluate_claim
    from app_panels.agent_panel import render_agent_panel
    result = evaluate_claim(claim_id)
    render_agent_panel(result)

Wording rule: the agent ASSESSES; only the insurer approves or denies.
"""

import streamlit as st

ROUTING_TEXT = {
    "ready_to_submit": "Ready to submit to the insurer. The insurer makes the final decision.",
    "request_documentation": "Request the missing information from the provider, then re-run.",
    "human_review": "Routed to a human reviewer before anything is submitted.",
}
BASIS_TEXT = {
    "policy": "policy",
    "policy_with_code_translation": "policy + code translation",
    "team_assumption": "TEAM ASSUMPTION",
}


def _short(chunk_id):
    return chunk_id.split("::", 1)[-1]


def render_agent_panel(result: dict) -> None:
    st.subheader("Agent assessment")
    st.caption("The agent assesses. It does not approve or deny; only the insurer does.")

    decision = result.get("decision") or "UNKNOWN"
    reason = result.get("decision_reason", "")
    box = {"MEETS_CRITERIA": st.success, "NEEDS_DOCS": st.warning}.get(decision, st.error)
    box(f"**{decision}**\n\n{reason}")

    routing = result.get("routing") or "unknown"
    st.markdown(f"**Routing:** `{routing}` — {ROUTING_TEXT.get(routing, '')}")

    rules = result.get("rules", [])
    st.markdown("#### Rules")
    if not rules:
        st.info("No rules were run. Without a matching policy the agent cannot assess this claim.")
    else:
        rows = []
        for i, r in enumerate(rules, 1):
            res = r["result"] + (" (red-flag exception)" if r.get("via") == "red_flag_exception" else "")
            rows.append({
                "#": i, "Rule": r["rule"], "Result": res,
                "Basis": BASIS_TEXT.get(r["basis"], r["basis"]),
                "What the agent saw": r.get("observed", ""),
                "Cited policy sections": "\n".join(_short(c) for c in r.get("cites_chunk", [])) or "none (team assumption)",
            })
        st.table(rows)
        with st.expander("Full chunk IDs cited by each rule"):
            for i, r in enumerate(rules, 1):
                st.markdown(f"**Rule {i}**")
                for c in r.get("cites_chunk", []):
                    mark = "" if r.get("citations_in_policy", True) else "  (NOT in retrieved policy)"
                    st.markdown(f"- `{c}`{mark}")
                if not r.get("cites_chunk"):
                    st.markdown("- none (team assumption, not from any policy)")

    if result.get("not_evaluated"):
        st.markdown("#### Not checked (no data for these)")
        for n in result["not_evaluated"]:
            st.markdown(f"- {n['item']}  *(team assumption)*" if n.get("basis") == "team_assumption"
                        else f"- {n['item']}")

    for w in result.get("warnings", []):
        st.warning(w)

    admin = result.get("admin") or {}
    if admin:
        st.markdown("#### Administrative elements")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Billing code**")
            st.info(admin.get("billing_code", "N/A"))
        with c2:
            ad = admin.get("auth_duration", {})
            st.markdown("**Authorization duration**")
            st.info(f"{ad.get('value', 'N/A')}  \n*({ad.get('basis', '').replace('_', ' ')})*")
        with c3:
            fu = admin.get("follow_up_plan", {})
            st.markdown("**Follow-up plan**")
            st.info(f"{fu.get('value', 'N/A')}  \n*({fu.get('basis', '').replace('_', ' ')})*")
        if admin.get("documentation_chunk"):
            st.caption(f"Documentation required: see policy section `{admin['documentation_chunk']}`")
