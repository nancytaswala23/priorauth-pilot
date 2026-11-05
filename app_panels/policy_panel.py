"""Policy panel for the Streamlit demo app (owner: Yashasvi).

Shows the output of retrieve_policy(). Called from app.py:

    from app_panels.policy_panel import render_policy_panel, load_search_models
    load_search_models()            # once, at start-up (cached)
    render_policy_panel(policy)     # policy = retrieve_policy(code, payer, state)
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "rag"))
from retrieve_policy import warm_up  # noqa: E402


@st.cache_resource(show_spinner="Loading policy search models (first run only)...")
def load_search_models():
    """Load the embedding + reranker models once per app session."""
    return warm_up()


def render_policy_panel(policy: dict) -> None:
    st.subheader("Policy retrieval")

    if not policy.get("found"):
        st.warning("**No policy found — route to human review.**\n\n" + policy.get("message", ""))
        st.caption(f"Payer: {policy.get('payer')} · Procedure: {policy.get('procedure_code')} · "
                   f"State: {policy.get('state')} → Medicare region {policy.get('patient_region') or '—'}")
        return

    badge = " &nbsp;`SYNTHETIC POLICY`" if policy.get("synthetic") else ""
    st.markdown(f"**{policy['policy_id']}**{badge}", unsafe_allow_html=True)

    st.markdown(f"**Payer:** {policy['payer']} &nbsp;·&nbsp; "
                f"**Procedure:** {policy['procedure_code']} &nbsp;·&nbsp; "
                f"**Policy region:** {policy.get('jurisdiction') or 'national'} &nbsp;·&nbsp; "
                f"**Patient region:** {policy.get('patient_region') or '—'}")

    st.caption(policy.get("message", ""))

    for i, s in enumerate(policy.get("sections", [])):
        label = s["section"] + (f"  ·  score {s['score']:.2f}" if s.get("score") is not None else "")
        with st.expander(label, expanded=(i == 0)):
            st.write(s["text"])
            st.caption(f"Chunk ID: `{s['chunk_id']}`")

    if any(s.get("score") is not None for s in policy.get("sections", [])):
        st.caption("Scores come from the reranker; only the order matters.")
    st.caption("Policies are synthetic, written by the team. Each section's chunk ID is what "
               "the agent's rules cite.")
