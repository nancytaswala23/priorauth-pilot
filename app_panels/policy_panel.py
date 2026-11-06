"""Policy panel for the Streamlit app (owner: Yashasvi).

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
from app_panels.ui import AMBER, CORAL, TEAL, badge, card, chip, esc, kpi_row  # noqa: E402

SECTION_ICONS = {
    "precertification": "📝", "medical necessity": "✅", "coverage": "✅", "red flag": "🚩",
    "limitation": "⛔", "not medically necessary": "⛔", "experimental": "🧪",
    "documentation": "📎", "background": "ℹ️",
}


@st.cache_resource(show_spinner="Loading policy search models (first run only)...")
def load_search_models():
    """Load the embedding + reranker models once per app session."""
    return warm_up()


def _icon(section):
    s = (section or "").lower()
    for key, icon in SECTION_ICONS.items():
        if key in s:
            return icon
    return "📄"


def render_policy_panel(policy: dict) -> None:
    if not policy.get("found"):
        routed = "Route to human review" in policy.get("message", "")
        headline = "No policy found — route to human review" if routed else "No policy in our library for this procedure"
        color = CORAL if routed else AMBER
        card(f"{badge(headline, color)}<p style='margin:12px 0 0 0'>{esc(policy.get('message', ''))}</p>",
             title="Policy result")
        kpi_row([("Payer", policy.get("payer") or "—"),
                 ("Procedure", policy.get("procedure_code") or "—"),
                 ("Patient state", policy.get("state") or "—"),
                 ("Medicare region", policy.get("patient_region") or "—")])
        return

    tags = badge("Policy found", TEAL) + "&nbsp;&nbsp;" + (chip("Synthetic policy") if policy.get("synthetic") else "")
    card(f"<div style='font-size:1.25rem;font-weight:700;color:#0B3C49;margin-bottom:10px'>"
         f"{esc(policy['policy_id'])}</div>{tags}"
         f"<p class='pa-muted' style='margin:10px 0 0 0'>{esc(policy.get('message', ''))}</p>",
         title="Matching policy")

    kpi_row([("Payer", policy["payer"]),
             ("Procedure", policy["procedure_code"]),
             ("Policy region", policy.get("jurisdiction") or "national"),
             ("Patient region", policy.get("patient_region") or "—")])

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown("#### Policy sections")
    for i, s in enumerate(policy.get("sections", [])):
        label = f"{_icon(s['section'])}  {s['section']}"
        if s.get("score") is not None:
            label += f"   ·   score {s['score']:.2f}"
        with st.expander(label, expanded=(i == 0)):
            st.write(s["text"])
            st.caption(f"Chunk ID: {s['chunk_id']}")

    if any(s.get("score") is not None for s in policy.get("sections", [])):
        st.caption("Scores come from the reranker; only the order matters.")