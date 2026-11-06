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
    """Get all claims for dropdown selector"""
    query = """
    SELECT DISTINCT claim_id, patient_id, procedure_code 
    FROM claims 
    ORDER BY claim_id
    """
    results = conn.execute(query).fetchall()
    return [f"{row[0]} (Patient {row[1]}, Procedure {row[2]})" for row in results], results

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

def render_data_panel():
    """Main data panel for Streamlit app"""
    
    st.header("📋 Data Panel - Patient & Claim Information")
    
    conn = load_duckdb()
    claim_options, claim_data = get_all_claims(conn)
    
    if not claim_options:
        st.error("No claims found in database")
        return None
    
    st.subheader("Select a Claim to Evaluate")
    selected_claim_text = st.selectbox("Choose a claim:", claim_options, key="claim_selector")
    
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
            st.write(f"**Red Flag Present:** {'✅ YES' if claim_details[5] else '❌ NO'}")
    else:
        st.error(f"Claim {claim_id} not found")
        return None
    
    return claim_id

if __name__ == "__main__":
    render_data_panel()
