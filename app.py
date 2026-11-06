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

# Page configuration
st.set_page_config(
    page_title="PriorAuthPilot Demo",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Title
st.markdown("# 🏥 PriorAuthPilot - Healthcare Prior Authorization AI")
st.markdown("*Automated compliance evaluation for prior authorization requests*")
st.markdown("---")

# Initialize session state
if 'claim_id' not in st.session_state:
    st.session_state.claim_id = None

if 'policy_data' not in st.session_state:
    st.session_state.policy_data = None

if 'evaluation_data' not in st.session_state:
    st.session_state.evaluation_data = None




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
1. **Select a claim** from the dropdown
2. **View patient & claim details** in the data panel
3. **Retrieve relevant policy** using RAG retrieval
4. **Evaluate compliance** against policy rules
5. **Get routing decision** (auto-approve, request docs, or human review)
""")

# ============================================================================
# MAIN CONTENT - TAB STRUCTURE
# ============================================================================
tab1, tab2, tab3, tab4 = st.tabs(["📋 Data", "📄 Policy", "⚖️ Evaluation", "✅ Summary"])

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
                                st.markdown(f"**Retrieval Score:** {policy_result.get('score', 'N/A')}")
                                
                                # Display policy sections
                                st.markdown("### Policy Sections Retrieved:")
                                
                                if policy_result.get("sections"):
                                    for i, section in enumerate(policy_result["sections"], 1):
                                        with st.expander(f"📌 Section {i}: {section.get('section', 'Policy Text')}"):
                                            st.markdown(f"**Chunk ID:** `{section.get('chunk_id', 'N/A')}`")
                                            st.markdown(f"**Retrieval Score:** {section.get('score', 'N/A')}")
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
# TAB 3: AGENT EVALUATION
# ============================================================================
with tab3:
    st.header("⚖️ Agent Evaluation & Decision")
    
    if st.session_state.claim_id:
        try:
            if st.button("🤖 Evaluate Claim", key="evaluate_btn"):
                with st.spinner("Evaluating claim against policy rules..."):
                    try:
                        evaluation_result = evaluate_claim(st.session_state.claim_id)
                        st.session_state.evaluation_data = evaluation_result
                        
                        if evaluation_result:
                            # Display decision prominently
                            decision = evaluation_result.get("decision", "UNKNOWN")
                            
                            if decision == "MEETS_CRITERIA":
                                st.success(f"✅ {decision}")
                            elif decision == "NEEDS_DOCS":
                                st.warning(f"⚠️ {decision}")
                            else:
                                st.error(f"❌ {decision}")
                            
                            # Display rules evaluation
                            st.markdown("### Rules Evaluation:")
                            rules = evaluation_result.get("rules", [])
                            
                            for i, rule in enumerate(rules, 1):
                                with st.expander(f"Rule {i}: {rule.get('rule', 'Unknown')}"):
                                    col1, col2, col3 = st.columns(3)
                                    
                                    with col1:
                                        st.markdown(f"**Basis:** {rule.get('basis', 'N/A')}")
                                    
                                    with col2:
                                        result = rule.get('result')
                                        if result == "PASS":
                                            st.markdown("✅ **Result:** PASS")
                                        else:
                                            st.markdown("❌ **Result:** FAIL")
                                    
                                    with col3:
                                        chunks = rule.get('cites_chunk', [])
                                        if chunks:
                                            st.markdown(f"**Citations:** {len(chunks)}")
                                    
                                    # Show chunk citations
                                    if rule.get('cites_chunk'):
                                        st.markdown("**Policy Sections Cited:**")
                                        for chunk in rule['cites_chunk']:
                                            st.markdown(f"- `{chunk}`")
                            
                            # Display decision reason
                            st.markdown("---")
                            st.markdown("### Decision Reason:")
                            st.info(evaluation_result.get("decision_reason", "No reason provided"))
                            
                            # Display routing
                            st.markdown("### Routing:")
                            routing = evaluation_result.get("routing", "unknown")
                            st.markdown(f"**Route to:** `{routing}`")
                    
                    except Exception as e:
                        st.error(f"Error evaluating claim: {str(e)}")
                        st.markdown("*Make sure evaluate_claim() is available in src/agent/*")
            
            # Display cached evaluation
            if st.session_state.evaluation_data:
                st.markdown("---")
                st.markdown("### 📊 Full Evaluation Data")
                
                with st.expander("View Raw JSON"):
                    st.json(st.session_state.evaluation_data)
        
        except Exception as e:
            st.error(f"Error: {str(e)}")
    else:
        st.info("👈 Please select a claim in the Data tab first")

# ============================================================================
# TAB 4: SUMMARY & ADMIN ELEMENTS
# ============================================================================
with tab4:
    st.header("✅ Prior Authorization Assessment Summary")
    
    if st.session_state.claim_id and st.session_state.evaluation_data:
        try:
            evaluation = st.session_state.evaluation_data
            policy = st.session_state.policy_data or {}
            
            conn = load_duckdb()
            claim_details = get_claim_details(conn, st.session_state.claim_id)
            patient_info = get_patient_info(conn, claim_details[1])
            
            # Main decision box
            st.markdown("### 📋 Decision")
            decision = evaluation.get("decision", "UNKNOWN")
            decision_color = "green" if decision == "MEETS_CRITERIA" else ("orange" if decision == "NEEDS_DOCS" else "red")
            
            st.markdown(f"""
            <div style="background-color: #f0f0f0; padding: 20px; border-radius: 10px; border-left: 4px solid {decision_color};">
                <h3 style="color: {decision_color};">{decision}</h3>
                <p><b>Reason:</b> {evaluation.get('decision_reason', 'N/A')}</p>
            </div>
            """, unsafe_allow_html=True)
            
            # Administrative Elements
            st.markdown("### 📌 Administrative Elements")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                admin = evaluation.get("admin", {})
                st.markdown("**Billing Code**")
                st.info(admin.get("billing_code", "N/A"))
            
            with col2:
                auth_duration = admin.get("auth_duration", {})
                st.markdown("**Authorization Duration**")
                st.info(f"{auth_duration.get('value', 'N/A')} ({auth_duration.get('basis', 'N/A')})")
            
            with col3:
                follow_up = admin.get("follow_up_plan", {})
                st.markdown("**Follow-up Plan**")
                st.info(f"{follow_up.get('basis', 'N/A')}")
            
            # Routing
            st.markdown("### 🔀 Routing Decision")
            routing = evaluation.get("routing", "unknown").upper()
            routing_text = {
                "AUTO_APPROVE": "✅ Automatically approved - no further action needed",
                "HUMAN_REVIEW": "👤 Routed to medical director for manual review",
                "REQUEST_DOCUMENTATION": "📄 Request additional documentation from provider",
            }
            st.warning(routing_text.get(routing, f"Route: {routing}"))
            
            # Policy Summary
            if policy and policy.get("found"):
                st.markdown("### 📄 Policy Summary")
                st.markdown(f"**Policy ID:** {policy.get('policy_id', 'N/A')}")
                st.markdown(f"**Payer:** {policy.get('payer', 'N/A')}")
                st.markdown(f"**Jurisdiction:** {policy.get('jurisdiction', 'National')}")
            
            # Export summary
            st.markdown("---")
            if st.button("📥 Export Summary as JSON"):
                summary = {
                    "claim_id": st.session_state.claim_id,
                    "decision": evaluation.get("decision"),
                    "routing": evaluation.get("routing"),
                    "admin": evaluation.get("admin"),
                    "policy": policy,
                }
                st.json(summary)
        
        except Exception as e:
            st.error(f"Error: {str(e)}")
    else:
        st.info("👈 Complete the Data and Evaluation tabs first to see the summary")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: gray;">
    <p><b>PriorAuthPilot Demo</b> | Mid-Term Research Paper Presentation | November 7, 2026</p>
    <p>Data sourced from Snowflake via DuckDB • RAG via FAISS • Agent via Rule Engine</p>
</div>
""", unsafe_allow_html=True)

