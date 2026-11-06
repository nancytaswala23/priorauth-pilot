"""
PriorAuthPilot - Streamlit Demo App
Main application integrating data panel, RAG policy retrieval, and agent evaluation.

Synthetic data and policies. The agent assesses requests; only the insurer approves or denies.
"""

import os
import sys

import streamlit as st

# Make the repo root and src/rag importable, whether app.py sits in the root or a subfolder
HERE = os.path.dirname(os.path.abspath(__file__))
for root in (HERE, os.path.dirname(HERE)):
    for path in (root, os.path.join(root, "src", "rag")):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

from src.ui.data_panel import render_data_panel, load_duckdb, get_claim_details, get_patient_info  # noqa: E402
from src.rag.retrieve_policy import retrieve_policy  # noqa: E402
from src.agent.evaluate_claim import evaluate_claim  # noqa: E402

# Yashasvi's policy panel: works whether it lives in src/ui/app_panels/ or app_panels/
try:
    from src.ui.app_panels.policy_panel import render_policy_panel, load_search_models  # noqa: E402
except ImportError:
    from app_panels.policy_panel import render_policy_panel, load_search_models  # noqa: E402

# Page configuration (must be the first Streamlit call)
st.set_page_config(
    page_title="PriorAuthPilot Demo",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load the policy search models once per session, so questions are answered quickly
load_search_models()

# Title
st.markdown("# 🏥 PriorAuthPilot - Prior Authorization Assistant")
st.markdown("*Checks a prior authorization request against the payer's policy before it is submitted*")
st.markdown("---")

# Session state
for key in ("claim_id", "policy_data", "evaluation_data"):
    if key not in st.session_state:
        st.session_state[key] = None


def show_admin_value(item):
    """Admin elements may be a plain value or {"value": ..., "basis": ...}."""
    if isinstance(item, dict):
        value = item.get("value", "N/A")
        basis = item.get("basis")
        return f"{value} ({basis})" if basis else str(value)
    return str(item) if item not in (None, "") else "N/A"


ROUTING_TEXT = {
    "submit": "✅ Meets criteria – ready to submit to the insurer",
    "ready_to_submit": "✅ Meets criteria – ready to submit to the insurer",
    "human_review": "👤 Routed to staff for human review",
    "request_documentation": "📄 Request additional documentation from the provider",
    "request_docs": "📄 Request additional documentation from the provider",
}


def routing_message(routing):
    return ROUTING_TEXT.get(str(routing or "").strip().lower(), f"Route: {routing}")


# ============================================================================
# SIDEBAR
# ============================================================================
st.sidebar.markdown("## 📊 Project Information")
st.sidebar.markdown("""
**PriorAuthPilot** - DAMG 6300, Northeastern University

**Team:**
- Nancy: Data Engineering
- Yashasvi: RAG & Policy Retrieval
- Rekha: Agent Orchestration

**GitHub:** nancytaswala23/priorauth-pilot

**Demo Date:** November 7, 2026
""")

st.sidebar.markdown("---")
st.sidebar.markdown("## 📖 How It Works")
st.sidebar.markdown("""
1. **Select a claim** in the Data tab
2. **View patient & claim details**
3. **Retrieve the policy** that applies (payer, procedure, region)
4. **Evaluate** the request against the policy rules
5. **Get a routing recommendation** (ready to submit, request docs, or human review)
""")
st.sidebar.markdown("---")
st.sidebar.caption("Synthetic data and policies. The agent assesses requests; "
                   "only the insurer approves or denies.")

# ============================================================================
# MAIN CONTENT - TABS
# ============================================================================
tab1, tab2, tab3, tab4 = st.tabs(["📋 Data", "📄 Policy", "⚖️ Evaluation", "✅ Summary"])

# ============================================================================
# TAB 1: DATA PANEL (Nancy)
# ============================================================================
with tab1:
    st.header("📋 Patient & Claim Information")
    try:
        claim_id = render_data_panel()
        if claim_id:
            # A new claim clears results from the previous claim
            if claim_id != st.session_state.claim_id:
                st.session_state.policy_data = None
                st.session_state.evaluation_data = None
            st.session_state.claim_id = claim_id
            st.success(f"✅ Claim {claim_id} selected. Proceed to the Policy tab →")
    except Exception as e:
        st.error(f"Error loading data: {e}")

# ============================================================================
# TAB 2: POLICY RETRIEVAL (Yashasvi's panel)
# ============================================================================
with tab2:
    st.header("📄 Policy Retrieval (RAG)")

    if st.session_state.claim_id:
        try:
            conn = load_duckdb()
            claim_details = get_claim_details(conn, st.session_state.claim_id)
            patient_info = get_patient_info(conn, claim_details[1]) if claim_details else None

            if claim_details and patient_info:
                procedure_code = claim_details[2]
                patient_state = patient_info[3]
                payer = patient_info[4]

                question = st.text_input(
                    "Optional: ask the policy a question (runs the FAISS + reranker search)",
                    placeholder="e.g. How many weeks of conservative treatment are needed before a lumbar MRI?",
                    key="policy_question",
                )
                with st.spinner("Retrieving policy..."):
                    policy_result = retrieve_policy(procedure_code, payer, patient_state, question or None)
                st.session_state.policy_data = policy_result

                render_policy_panel(policy_result)

                with st.expander("View raw JSON"):
                    st.json(policy_result)
            else:
                st.warning("Claim or patient not found in the database.")
        except Exception as e:
            st.error(f"Error retrieving policy: {e}")
    else:
        st.info("👈 Please select a claim in the Data tab first")

# ============================================================================
# TAB 3: AGENT EVALUATION (Rekha)
# ============================================================================
with tab3:
    st.header("⚖️ Agent Assessment")

    if st.session_state.claim_id:
        if st.button("🤖 Evaluate Claim", key="evaluate_btn"):
            with st.spinner("Evaluating claim against policy rules..."):
                try:
                    st.session_state.evaluation_data = evaluate_claim(st.session_state.claim_id)
                except Exception as e:
                    st.session_state.evaluation_data = None
                    st.error(f"Error evaluating claim: {e}")

        # Results stay visible after other interactions (they are kept in session state)
        evaluation_result = st.session_state.evaluation_data
        if evaluation_result:
            decision = evaluation_result.get("decision", "UNKNOWN")
            if decision == "MEETS_CRITERIA":
                st.success(f"✅ {decision}")
            elif decision == "NEEDS_DOCS":
                st.warning(f"⚠️ {decision}")
            else:
                st.error(f"❌ {decision}")
            st.caption("This is the agent's assessment, not an approval or denial. "
                       "Only the insurer approves or denies.")

            st.markdown("### Rules Evaluation")
            for i, rule in enumerate(evaluation_result.get("rules", []), 1):
                with st.expander(f"Rule {i}: {rule.get('rule', 'Unknown')}"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.markdown(f"**Basis:** {rule.get('basis', 'N/A')}")
                    with col2:
                        if rule.get("result") == "PASS":
                            st.markdown("✅ **Result:** PASS")
                        else:
                            st.markdown("❌ **Result:** FAIL")
                    with col3:
                        chunks = rule.get("cites_chunk") or []
                        st.markdown(f"**Citations:** {len(chunks)}")
                    if chunks:
                        st.markdown("**Policy sections cited:**")
                        for chunk in chunks:
                            st.markdown(f"- `{chunk}`")
                    if rule.get("basis") == "team_assumption":
                        st.caption("Team assumption: not stated in any policy.")

            st.markdown("---")
            st.markdown("### Decision Reason")
            st.info(evaluation_result.get("decision_reason", "No reason provided"))

            st.markdown("### Routing")
            st.markdown(routing_message(evaluation_result.get("routing")))

            with st.expander("View raw JSON"):
                st.json(evaluation_result)
    else:
        st.info("👈 Please select a claim in the Data tab first")

# ============================================================================
# TAB 4: SUMMARY & ADMIN ELEMENTS
# ============================================================================
with tab4:
    st.header("✅ Prior Authorization Assessment Summary")

    evaluation = st.session_state.evaluation_data
    if st.session_state.claim_id and evaluation:
        try:
            policy = st.session_state.policy_data or {}

            st.markdown("### 📋 Assessment")
            decision = evaluation.get("decision", "UNKNOWN")
            decision_color = ("green" if decision == "MEETS_CRITERIA"
                              else "orange" if decision == "NEEDS_DOCS" else "red")
            st.markdown(f"""
            <div style="background-color: #f0f0f0; padding: 20px; border-radius: 10px;
                        border-left: 4px solid {decision_color};">
                <h3 style="color: {decision_color};">{decision}</h3>
                <p><b>Reason:</b> {evaluation.get('decision_reason', 'N/A')}</p>
                <p style="color: gray; font-size: 0.9em;">Agent assessment, not an approval or denial.</p>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("### 📌 Administrative Elements")
            admin = evaluation.get("admin", {}) or {}
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown("**Billing Code**")
                st.info(show_admin_value(admin.get("billing_code")))
            with col2:
                st.markdown("**Authorization Duration**")
                st.info(show_admin_value(admin.get("auth_duration")))
            with col3:
                st.markdown("**Follow-up Plan**")
                st.info(show_admin_value(admin.get("follow_up_plan")))
            st.caption("Items marked team_assumption are not stated in any policy.")

            st.markdown("### 🔀 Routing")
            st.warning(routing_message(evaluation.get("routing")))

            if policy.get("found"):
                st.markdown("### 📄 Policy Summary")
                st.markdown(f"**Policy ID:** {policy.get('policy_id', 'N/A')}"
                            + ("  `SYNTHETIC POLICY`" if policy.get("synthetic") else ""))
                st.markdown(f"**Payer:** {policy.get('payer', 'N/A')}")
                st.markdown(f"**Policy region:** {policy.get('jurisdiction') or 'national'}  ·  "
                            f"**Patient region:** {policy.get('patient_region') or '—'}")
            elif policy:
                st.markdown("### 📄 Policy Summary")
                st.warning(policy.get("message", "No policy found."))

            st.markdown("---")
            if st.button("📥 Export Summary as JSON"):
                st.json({
                    "claim_id": st.session_state.claim_id,
                    "decision": evaluation.get("decision"),
                    "routing": evaluation.get("routing"),
                    "admin": evaluation.get("admin"),
                    "policy": policy,
                })
        except Exception as e:
            st.error(f"Error: {e}")
    else:
        st.info("👈 Select a claim and run the evaluation first to see the summary")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: gray;">
    <p><b>PriorAuthPilot Demo</b> | Mid-Term Research Paper Presentation | November 7, 2026</p>
    <p>Synthetic data and policies • Data from Snowflake via DuckDB • Policy search via FAISS + reranker • Rule-based agent</p>
    <p>The agent assesses requests; only the insurer approves or denies.</p>
</div>
""", unsafe_allow_html=True)