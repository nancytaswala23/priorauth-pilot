"""
Data Panel for PriorAuthPilot Streamlit App
Displays patient demographics and claim details
"""

import streamlit as st
import duckdb

def load_duckdb():
    """Load DuckDB connection"""
    conn = duckdb.connect('priorauth.duckdb')
    return conn

def get_all_claims(conn):
    """All claims for the selector, joined to the patient so they can be searched
    by payer and state as well as by claim, patient and procedure code."""
    query = """
    SELECT c.claim_id, c.patient_id, c.procedure_code, p.insurance, p.state
    FROM claims c
    LEFT JOIN patients p ON p.patient_id = c.patient_id
    ORDER BY c.claim_id
    """
    rows = conn.execute(query).fetchall()
    labels = [f"{r[0]} (Patient {r[1]}, Procedure {r[2]}, {r[3]}, {r[4]})" for r in rows]
    return labels, rows


def filter_claims(labels, rows, text):
    """Keep claims that match EVERY word typed (so 'medicare 72148' works).
    Short words (1-2 letters, e.g. a state like 'CA') must match the START of a field,
    so 'ca' finds California but not 'Medicare'. Longer words match anywhere in a field."""
    words = (text or "").lower().split()
    if not words:
        return labels, rows
    keep = []
    for i, r in enumerate(rows):
        fields = [str(x).lower() for x in r]   # claim, patient, procedure, payer, state
        ok = True
        for w in words:
            hit = any(f.startswith(w) for f in fields) if len(w) < 3 else any(w in f for f in fields)
            if not hit:
                ok = False
                break
        if ok:
            keep.append(i)
    return [labels[i] for i in keep], [rows[i] for i in keep]


def get_patient_info(conn, patient_id):
    """Get patient demographics"""
    query = f"""
    SELECT patient_id, age, gender, state, insurance 
    FROM patients 
    WHERE patient_id = '{patient_id}'
    """
    return conn.execute(query).fetchone()

def get_claim_details(conn, claim_id):
    """Get full claim details"""
    query = f"""
    SELECT claim_id, patient_id, procedure_code, diagnosis_code, 
           conservative_treatment_weeks, red_flag_present, date_of_service
    FROM claims 
    WHERE claim_id = '{claim_id}'
    """
    return conn.execute(query).fetchone()

def get_procedure_name(conn, procedure_code):
    """Get procedure name from procedure code"""
    query = f"""
    SELECT procedure_code, procedure_name, cost
    FROM procedures 
    WHERE procedure_code = '{procedure_code}'
    """
    result = conn.execute(query).fetchone()
    if result:
        return result[1], result[2]
    return f"Code {procedure_code}", "N/A"

def _is_true(value):
    """red_flag_present is a BOOLEAN in DuckDB; also accept 'TRUE' / 1 just in case."""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "t", "1", "yes")
    return bool(value)


def render_data_panel():
    """Main data panel for Streamlit app"""
    
    st.header("📋 Data Panel - Patient & Claim Information")
    
    conn = load_duckdb()
    all_options, all_data = get_all_claims(conn)

    if not all_options:
        st.error("No claims found in database")
        return None

    st.subheader("Select a Claim to Evaluate")

    query = st.text_input(
        "🔍 Search claims",
        key="claim_search",
        placeholder="Claim ID, patient ID, procedure code, payer or state  (e.g. C10001, P1000, 72148, Medicare, NY)",
        help="Type several words to narrow down, e.g. 'medicare 72148'.",
    )
    claim_options, claim_data = filter_claims(all_options, all_data, query)

    if not claim_options:
        st.warning(f"No claims match \u201c{query}\u201d. Try fewer words, or clear the search box.")
        return None

    if query.strip():
        st.caption(f"{len(claim_options)} of {len(all_options)} claims match")

    # The key includes the search text so the list resets to its first match when the search changes.
    selected_claim_text = st.selectbox("Choose a claim:", claim_options,
                                       key=f"claim_selector::{query.strip().lower()}")
    
    selected_index = claim_options.index(selected_claim_text)
    claim_id = claim_data[selected_index][0]
    patient_id = claim_data[selected_index][1]
    procedure_code = claim_data[selected_index][2]
    
    st.subheader("👤 Patient Demographics")
    patient_info = get_patient_info(conn, patient_id)
    
    if patient_info:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Patient ID", patient_id)
        with col2:
            st.metric("Age", patient_info[1])
        with col3:
            st.metric("Gender", patient_info[2])
        with col4:
            st.metric("State", patient_info[3])
        
        st.write(f"**Insurance:** {patient_info[4]}")
    else:
        st.error(f"Patient {patient_id} not found")
        return None
    
    st.subheader("📄 Claim Details")
    claim_details = get_claim_details(conn, claim_id)
    
    if claim_details:
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**Claim ID:** {claim_details[0]}")
            st.write(f"**Date of Service:** {claim_details[6]}")
            
            proc_name, proc_cost = get_procedure_name(conn, procedure_code)
            st.write(f"**Procedure Code:** {procedure_code}")
            st.write(f"**Procedure:** {proc_name}")
            st.write(f"**Cost:** {proc_cost}")
        
        with col2:
            st.write(f"**Diagnosis Code:** {claim_details[3]}")
            st.write(f"**Conservative Treatment Weeks:** {claim_details[4]}")
            st.write(f"**Red Flag Present:** {'✅ YES' if _is_true(claim_details[5]) else '❌ NO'}")
    else:
        st.error(f"Claim {claim_id} not found")
        return None
    
    return claim_id

if __name__ == "__main__":
    render_data_panel()
    