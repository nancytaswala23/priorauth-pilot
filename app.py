"""
PriorAuthPilot - Streamlit Demo App
Main application integrating data panel, RAG policy retrieval, and agent evaluation
"""

import streamlit as st
import duckdb
import sys
import os

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.ui.data_panel import render_data_panel, load_duckdb, get_claim_details, get_patient_info
from src.rag.retrieve_policy import retrieve_policy
from src.agent.evaluate_claim import evaluate_claim
from app_panels.agent_panel import render_agent_panel

# Page configuration
st.set_page_config(
    page_title="PriorAuthPilot Demo",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Title
st.markdown("# 🏥 PriorAuthPilot - Healthcare Prior Authorization AI")
st.markdown("*Automated assessment of prior authorization requests*")
st.markdown("---")

# Initialize session state
if 'claim_id' not in st.session_state:
    st.session_state.claim_id = None

if 'policy_data' not in st.session_state:
    st.session_state.policy_data = None

if 'evaluation_data' not in st.session_state:
    st.session_state.evaluation_data = None




# ============================================================================
# SIDEBAR - team names only
# ============================================================================
st.sidebar.markdown("## PriorAuthPilot")
st.sidebar.markdown("""
**Team**
- Nancy Taswala
- Yashasvi Nagar
- Avadhanam Vinaya Rekha
""")

# ============================================================================
# MAIN CONTENT - TAB STRUCTURE
# ============================================================================
tab1, tab2, tab3, tab4 = st.tabs(["📋 Data", "📄 Policy", "⚖️ Assessment", "✅ Summary"])

# ============================================================================
# TAB 1: DATA PANEL
# ============================================================================
with tab1:
    st.header("📋 Patient & Claim Information")
    
    try:
        # Render data panel and get claim_id
        claim_id = render_data_panel()
        
        if claim_id:
            st.session_state.claim_id = claim_id
            st.success(f"✅ Claim {claim_id} selected. Proceed to Policy tab →")
    
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")

# ============================================================================
# TAB 2: POLICY RETRIEVAL (RAG)
# ============================================================================
with tab2:
    st.header("📄 Policy Retrieval (RAG)")
    
    if st.session_state.claim_id:
        try:
            conn = load_duckdb()
            claim_details = get_claim_details(conn, st.session_state.claim_id)
            patient_info = get_patient_info(conn, claim_details[1])
            
            if claim_details and patient_info:
                procedure_code = claim_details[2]
                patient_state = patient_info[3]
                payer = patient_info[4]  # insurance company
                
                st.markdown(f"### Retrieving policy for:")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Procedure", procedure_code)
                with col2:
                    st.metric("Payer", payer)
                with col3:
                    st.metric("State", patient_state)
                with col4:
                    st.metric("Patient", claim_details[1])
                
                # Retrieve policy
                if st.button("🔍 Retrieve Policy", key="retrieve_btn"):
                    with st.spinner("Searching policy database..."):
                        try:
                            policy_result = retrieve_policy(procedure_code, payer, patient_state)
                            st.session_state.policy_data = policy_result
                            
                            if policy_result.get("found"):
                                st.success("✅ Policy found!")
                                
                                # Display policy info
                                st.markdown(f"**Policy ID:** {policy_result['policy_id']}")
                                st.markdown(f"**Jurisdiction:** {policy_result.get('jurisdiction', 'National')}")
                                
                                # Display policy sections
                                st.markdown("### Policy Sections Retrieved:")
                                
                                if policy_result.get("sections"):
                                    for i, section in enumerate(policy_result["sections"], 1):
                                        with st.expander(f"📌 Section {i}: {section.get('section', 'Policy Text')}"):
                                            st.markdown(f"**Chunk ID:** `{section.get('chunk_id', 'N/A')}`")
                                            if section.get("score") is not None:
                                                st.markdown(f"**Reranker score:** {section['score']:.2f} (only the order matters)")
                                            st.markdown(f"\n{section.get('text', 'No text available')}")
                            else:
                                st.warning(f"⚠️ No policy found")
                                st.markdown(f"**Message:** {policy_result.get('message', 'No policy available for this combination')}")
                                st.markdown("**Routing:** Human review required")
                        
                        except Exception as e:
                            st.error(f"Error retrieving policy: {str(e)}")
                            st.markdown("*Make sure retrieve_policy() is available in src/rag/*")
                
                # Display cached policy
                if st.session_state.policy_data:
                    st.markdown("---")
                    st.markdown("### 📌 Current Policy Data")
                    
                    if st.session_state.policy_data.get("found"):
                        st.json(st.session_state.policy_data)
        
        except Exception as e:
            st.error(f"Error: {str(e)}")
    else:
        st.info("👈 Please select a claim in the Data tab first")

# ============================================================================
# TAB 3: AGENT ASSESSMENT
# ============================================================================
with tab3:
    st.header("⚖️ Agent Assessment")

    if st.session_state.claim_id:
        if st.button("🤖 Evaluate Claim", key="evaluate_btn"):
            with st.spinner("Assessing claim against policy rules..."):
                try:
                    st.session_state.evaluation_data = evaluate_claim(st.session_state.claim_id)
                except Exception as e:
                    st.session_state.evaluation_data = None
                    st.error(f"Error evaluating claim: {str(e)}")

        # Only show a result that belongs to the claim currently selected.
        evaluation = st.session_state.evaluation_data
        if evaluation and evaluation.get("claim_id") == st.session_state.claim_id:
            render_agent_panel(evaluation)
            with st.expander("View raw JSON"):
                st.json(evaluation)
        else:
            st.info("Click **Evaluate Claim** to assess the selected claim.")
    else:
        st.info("👈 Please select a claim in the Data tab first")

# ============================================================================
# TAB 4: SUMMARY & ADMIN ELEMENTS
# ============================================================================
ROUTING_TEXT = {
    "READY_TO_SUBMIT": "✅ Ready to submit to the insurer. The insurer makes the final decision.",
    "REQUEST_DOCUMENTATION": "📄 Request the missing information from the provider, then re-run the assessment.",
    "HUMAN_REVIEW": "👤 Routed to a human reviewer before anything is submitted.",
}

with tab4:
    st.header("✅ Prior Authorization Assessment Summary")

    evaluation = st.session_state.evaluation_data
    if st.session_state.claim_id and evaluation and evaluation.get("claim_id") == st.session_state.claim_id:
        try:
            # The policy comes from the evaluation itself, so it always matches this claim.
            policy = evaluation.get("policy") or {}

            st.markdown("### 📋 Assessment")
            assessment = evaluation.get("decision", "UNKNOWN")
            color = "green" if assessment == "MEETS_CRITERIA" else ("orange" if assessment == "NEEDS_DOCS" else "red")

            st.markdown(f"""
            <div style="background-color: #f0f0f0; padding: 20px; border-radius: 10px; border-left: 4px solid {color};">
                <h3 style="color: {color};">{assessment}</h3>
                <p><b>Reason:</b> {evaluation.get('decision_reason', 'N/A')}</p>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("### 📌 Administrative Elements")
            admin = evaluation.get("admin", {})
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown("**Billing Code**")
                st.info(admin.get("billing_code", "N/A"))
            with col2:
                auth_duration = admin.get("auth_duration", {})
                st.markdown("**Authorization Duration**")
                st.info(f"{auth_duration.get('value', 'N/A')} ({auth_duration.get('basis', 'N/A').replace('_', ' ')})")
            with col3:
                follow_up = admin.get("follow_up_plan", {})
                st.markdown("**Follow-up Plan**")
                st.info(f"{follow_up.get('value', 'N/A')} ({follow_up.get('basis', 'N/A').replace('_', ' ')})")

            st.markdown("### 🔀 Routing")
            routing = str(evaluation.get("routing", "unknown")).upper()
            st.warning(ROUTING_TEXT.get(routing, f"Route: {routing}"))

            st.markdown("### 📄 Policy Summary")
            st.markdown(f"**Payer:** {evaluation.get('payer', 'N/A')}")
            if policy.get("found"):
                st.markdown(f"**Policy ID:** {policy.get('policy_id', 'N/A')}")
                st.markdown(f"**Jurisdiction:** {policy.get('jurisdiction', 'National')}")
            else:
                st.warning(policy.get("message") or "No policy found. Route to human review.")

            st.markdown("---")
            if st.button("📥 Export Assessment as JSON"):
                st.json({
                    "claim_id": evaluation.get("claim_id"),
                    "assessment": evaluation.get("decision"),
                    "routing": evaluation.get("routing"),
                    "admin": evaluation.get("admin"),
                    "policy": policy,
                })

        except Exception as e:
            st.error(f"Error: {str(e)}")
    else:
        st.info("👈 Select a claim, then click Evaluate Claim in the Assessment tab to see the summary")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: gray;">
    <p><b>PriorAuthPilot Demo</b> | Mid-Term Research Paper Presentation | November 7, 2026</p>
    <p>Synthetic data and policies. The agent assesses; only the insurer approves or denies.<br>Data: local DuckDB copy of the Snowflake warehouse • Policies: FAISS retrieval • Agent: deterministic rules</p>
</div>
""", unsafe_allow_html=True)

