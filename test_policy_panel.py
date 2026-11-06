import sys; sys.path.insert(0, 'src/rag')
import streamlit as st
from retrieve_policy import retrieve_policy
from app_panels.policy_panel import render_policy_panel, load_search_models
load_search_models()
st.title('Policy panel test')
case = st.selectbox('Case', ['72149 SampleCommercial CA', '72148 Medicare MA', '72148 Medicare CA'])
code, payer, state = case.split()
render_policy_panel(retrieve_policy(code, payer, state))
