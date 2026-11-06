"""
PriorAuthPilot - Streamlit app
Data (Nancy) -> Policy retrieval (Yashasvi) -> Assessment (Rekha) -> Summary + PDF report.

Synthetic data and policies. The agent assesses; only the insurer approves or denies.
"""

import base64
import os
import sys

import streamlit as st

# Make the repo root and src/rag importable
HERE = os.path.dirname(os.path.abspath(__file__))
for root in (HERE, os.path.dirname(HERE)):
    for path in (root, os.path.join(root, "src", "rag")):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

from src.ui.data_panel import load_duckdb  # noqa: E402
from rag_pipeline import load_config  # noqa: E402
from src.rag.retrieve_policy import retrieve_policy  # noqa: E402
from src.agent.evaluate_claim import evaluate_claim  # noqa: E402
from app_panels.policy_panel import render_policy_panel, load_search_models  # noqa: E402
from app_panels.report_pdf import build_assessment_pdf  # noqa: E402
from app_panels.ui import (AMBER, CORAL, GREY, NAVY, TEAL, badge, card, chip, esc,  # noqa: E402
                           inject_css, kpi_row, kv_card, pill, section_title, stepper)

# ---------------------------------------------------------------- page setup
ASSETS = os.path.join(HERE, "assets")
ICON_PATH = os.path.join(ASSETS, "logo_icon.png")
LOGO_PATH = os.path.join(ASSETS, "logo_horizontal.png")
HAS_LOGO = os.path.exists(ICON_PATH)

st.set_page_config(page_title="PriorAuthPilot", page_icon=ICON_PATH if HAS_LOGO else "🏥",
                   layout="wide", initial_sidebar_state="expanded")
if HAS_LOGO and hasattr(st, "logo"):
    st.logo(LOGO_PATH, icon_image=ICON_PATH)
inject_css()
load_search_models()

for key in ("claim_id", "policy_data", "evaluation_data"):
    if key not in st.session_state:
        st.session_state[key] = None

# Header banner
icon_html = ""
if HAS_LOGO:
    with open(ICON_PATH, "rb") as f:
        icon_html = (f"<img src='data:image/png;base64,{base64.b64encode(f.read()).decode()}' "
                     f"width='60' style='border-radius:14px'>")
st.markdown(f"""
<div style="display:flex;align-items:center;gap:18px;padding:18px 24px;border-radius:18px;background:{NAVY};margin-bottom:18px">
  {icon_html}
  <div>
    <div style="color:#FFFFFF;font-size:1.9rem;font-weight:700;line-height:1.15">PriorAuth<span style="color:#7FC8BF">Pilot</span></div>
    <div style="color:#CFE7E3;font-size:0.98rem">Checks a prior authorization request against the payer's policy before it is submitted</div>
  </div>
</div>""", unsafe_allow_html=True)

# ---------------------------------------------------------------- data access
PROCEDURE_NAMES = {
    "72148": "Lumbar spine MRI, without contrast",
    "72149": "Lumbar spine MRI, with contrast",
    "72158": "Lumbar spine MRI, without and with contrast",
    "99213": "Office visit, established patient",
    "99214": "Office visit, established patient",
}


def procedure_label(code):
    code = str(code)
    return f"{code} · {PROCEDURE_NAMES[code]}" if code in PROCEDURE_NAMES else code


@st.cache_data(show_spinner=False)
def policy_codes():
    """Procedure codes covered by our policy library."""
    codes = set()
    for p in load_config()["policies"]:
        codes.update(str(c) for c in (p.get("procedure_codes") or [p["procedure_code"]]))
    return codes


@st.cache_data(show_spinner=False)
def list_claims():
    conn = load_duckdb()
    return conn.execute("""
        SELECT c.claim_id, c.patient_id, CAST(c.procedure_code AS VARCHAR) AS procedure_code, p.insurance
        FROM CLAIMS c JOIN PATIENTS p ON c.patient_id = p.patient_id
        ORDER BY c.claim_id""").fetchall()


def claim_record(claim_id):
    """One claim joined with its patient, as a dict keyed by column name."""
    try:
        conn = load_duckdb()
        df = conn.execute("""
            SELECT c.claim_id, c.patient_id, CAST(c.procedure_code AS VARCHAR) AS procedure_code,
                   c.diagnosis_code, c.date_of_service, c.conservative_treatment_weeks, c.red_flag_present,
                   p.age, p.gender, p.state, p.insurance
            FROM CLAIMS c JOIN PATIENTS p ON c.patient_id = p.patient_id
            WHERE c.claim_id = ?""", [claim_id]).fetchdf()
        return df.iloc[0].to_dict() if len(df) else {}
    except Exception:
        return {}


def patient_history(patient_id):
    conn = load_duckdb()
    return conn.execute("""
        SELECT claim_id AS "Claim", CAST(procedure_code AS VARCHAR) AS "Procedure",
               diagnosis_code AS "Diagnosis", date_of_service AS "Date of service",
               conservative_treatment_weeks AS "Treatment (weeks)", red_flag_present AS "Red flag"
        FROM CLAIMS WHERE patient_id = ? ORDER BY date_of_service DESC""", [patient_id]).fetchdf()


def is_true(value):
    return str(value).strip().lower() in ("true", "1")


# ---------------------------------------------------------------- sidebar: claim selection
with st.sidebar:
    st.markdown("### Select a claim")
    try:
        claims = list_claims()
    except Exception as e:
        claims = []
        st.error(f"Could not load claims: {e}")
    only_pa = st.toggle("Only procedures in our policy library", value=True,
                        help="Hides claims like office visits that our policies do not cover.")
    shown = [c for c in claims if not only_pa or c[2] in policy_codes()]
    if shown:
        ids = [c[0] for c in shown]
        labels = {c[0]: f"{c[0]}  ·  {c[1]}  ·  {c[2]}" for c in shown}
        current = st.session_state.claim_id
        default = ids.index(current) if current in ids else (ids.index("C10001") if "C10001" in ids else 0)
        picked = st.selectbox("Claim", ids, index=default, format_func=lambda cid: labels[cid])
        if picked != st.session_state.claim_id:
            st.session_state.policy_data = None
        st.session_state.claim_id = picked

        rec = claim_record(picked)
        if rec:
            st.markdown(
                f"<div class='pa-card' style='padding:14px 16px;margin-top:6px'>"
                f"<div class='pa-card-title'>Selected</div>"
                f"<div style='font-weight:700;color:#0B3C49'>{esc(rec['claim_id'])} · {esc(rec['patient_id'])}</div>"
                f"<div class='pa-muted'>{esc(procedure_label(rec['procedure_code']))}</div>"
                f"<div class='pa-muted'>{esc(rec['insurance'])} · {esc(rec['state'])}</div></div>",
                unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("**Team**  \nNancy Taswala  \nYashasvi Nagar  \nAvadhanam Vinaya Rekha")

# ---------------------------------------------------------------- helpers
DECISION_STYLE = {
    "MEETS_CRITERIA": ("Meets criteria", TEAL, "✅"),
    "NEEDS_DOCS": ("Needs documentation", AMBER, "📄"),
    "DOES_NOT_MEET_CRITERIA": ("Does not meet criteria", CORAL, "⚠️"),
}
ROUTING_TEXT = {
    "READY_TO_SUBMIT": "Ready to submit to the insurer. The insurer makes the final decision.",
    "REQUEST_DOCUMENTATION": "Request the missing information from the provider, then run the assessment again.",
    "HUMAN_REVIEW": "Send to a staff member for review before anything is submitted.",
}
ROUTING_ICON = {"READY_TO_SUBMIT": "✅", "REQUEST_DOCUMENTATION": "📄", "HUMAN_REVIEW": "👤"}
BASIS_LABEL = {"policy": "Policy", "policy_with_code_translation": "Policy · code mapping",
               "team_assumption": "Team assumption"}


def routing_parts(routing):
    key = str(routing or "").strip().upper()
    return ROUTING_ICON.get(key, "➡️"), ROUTING_TEXT.get(key, f"Next step: {routing}")


def friendly_rule(rule_text):
    r = (rule_text or "").lower()
    if "conservative_treatment_weeks" in r:
        return "At least 6 weeks of conservative treatment, or a red flag"
    if "diagnosis" in r:
        return "Qualifying diagnosis (radiculopathy), or a red flag"
    if "age" in r:
        return "Patient is 18 or older"
    return rule_text or "Rule"


def rule_citations(rule):
    cites = []
    for key, value in rule.items():
        if key.endswith("cites_chunk") and value:
            cites += value if isinstance(value, list) else [value]
    return cites


def admin_value(item):
    if isinstance(item, dict):
        basis = item.get("basis")
        return item.get("value") or "N/A", (basis.replace("_", " ") if basis else None)
    return (item or "N/A"), None


def claim_facts(claim_id):
    rec = claim_record(claim_id)
    if not rec:
        return {}
    return {"Patient": rec["patient_id"], "Procedure": rec["procedure_code"], "Diagnosis": rec["diagnosis_code"],
            "Treatment": f"{rec['conservative_treatment_weeks']} weeks",
            "Red flag": "Yes" if is_true(rec["red_flag_present"]) else "No",
            "Age": rec["age"], "Gender": rec["gender"], "State": rec["state"], "Payer": rec["insurance"]}


def current_evaluation():
    ev = st.session_state.evaluation_data
    return ev if ev and ev.get("claim_id") == st.session_state.claim_id else None


def progress():
    policy = st.session_state.policy_data
    return [bool(st.session_state.claim_id), bool(policy and policy.get("found")),
            bool(current_evaluation()), bool(current_evaluation())]


def decision_style(ev):
    return DECISION_STYLE.get(ev.get("decision"), (ev.get("decision") or "Unknown", GREY, "•"))


# ---------------------------------------------------------------- tabs
tab1, tab2, tab3, tab4 = st.tabs(["📋  Data", "📄  Policy", "⚖️  Assessment", "✅  Summary"])

# ===== TAB 1: DATA (Nancy) =====
with tab1:
    stepper(0, progress())
    section_title("📋", "Patient & claim", "Pick a claim in the sidebar to see its details")
    if not st.session_state.claim_id:
        st.info("👈 Select a claim in the sidebar")
    else:
        rec = claim_record(st.session_state.claim_id)
        if not rec:
            st.warning("Claim not found in the database.")
        else:
            in_library = rec["procedure_code"] in policy_codes()
            coverage = (chip("Covered by our policy library") if in_library
                        else chip("Not in our policy library"))
            left, right = st.columns(2)
            with left:
                kv_card("Patient", [
                    ("Patient ID", rec["patient_id"]),
                    ("Age", rec["age"]),
                    ("Gender", rec["gender"]),
                    ("State", rec["state"]),
                    ("Insurance", rec["insurance"]),
                ])
            with right:
                kv_card("This claim", [
                    ("Claim ID", rec["claim_id"]),
                    ("Procedure", procedure_label(rec["procedure_code"])),
                    ("Diagnosis code", rec["diagnosis_code"]),
                    ("Date of service", rec["date_of_service"]),
                    ("Conservative treatment", f"{rec['conservative_treatment_weeks']} weeks"),
                    ("Red flag present", "Yes" if is_true(rec["red_flag_present"]) else "No"),
                ], footer_html=coverage)

            st.markdown("#### Patient's claim history")
            try:
                hist = patient_history(rec["patient_id"])
                hist["Red flag"] = hist["Red flag"].map(lambda v: "Yes" if is_true(v) else "No")
                st.dataframe(hist, hide_index=True, use_container_width=True)
            except Exception as e:
                st.caption(f"Claim history unavailable: {e}")
            st.success("Continue to the **Policy** tab to find the payer's policy for this claim.")

# ===== TAB 2: POLICY (Yashasvi) =====
with tab2:
    stepper(1, progress())
    section_title("📄", "Policy", "The payer's policy that applies to this claim")
    if not st.session_state.claim_id:
        st.info("👈 Select a claim in the sidebar first")
    else:
        try:
            rec = claim_record(st.session_state.claim_id)
            if rec:
                question = st.text_input(
                    "🔎  Ask the policy a question (optional)",
                    placeholder="e.g. How many weeks of conservative treatment are needed before a lumbar MRI?",
                    key="policy_question")
                with st.spinner("Finding the matching policy..."):
                    policy_result = retrieve_policy(rec["procedure_code"], rec["insurance"], rec["state"], question or None)
                st.session_state.policy_data = policy_result
                render_policy_panel(policy_result)
                with st.expander("Technical details (JSON)"):
                    st.json(policy_result)
            else:
                st.warning("Claim or patient not found in the database.")
        except Exception as e:
            st.error(f"Could not retrieve the policy: {e}")

# ===== TAB 3: ASSESSMENT (Rekha) =====
with tab3:
    stepper(2, progress())
    section_title("⚖️", "Assessment", "Checks the claim against the policy rules")
    if not st.session_state.claim_id:
        st.info("👈 Select a claim in the sidebar first")
    else:
        if st.button("Run assessment", type="primary", key="evaluate_btn"):
            with st.spinner("Checking the claim against the policy rules..."):
                try:
                    st.session_state.evaluation_data = evaluate_claim(st.session_state.claim_id)
                except Exception as e:
                    st.session_state.evaluation_data = None
                    st.error(f"Could not assess this claim: {e}")

        ev = current_evaluation()
        if ev:
            label, color, icon = decision_style(ev)
            r_icon, r_text = routing_parts(ev.get("routing"))
            card(f"{badge(f'{icon}  {label}', color)}"
                 f"<p style='margin:14px 0 6px 0'><b>Why:</b> {esc(ev.get('decision_reason', '—'))}</p>"
                 f"<p style='margin:0'><b>Next step:</b> {r_icon} {esc(r_text)}</p>",
                 title="Result")

            facts = claim_facts(ev["claim_id"])
            if facts:
                kpi_row([("Conservative treatment", facts["Treatment"]), ("Red flag", facts["Red flag"]),
                         ("Diagnosis", facts["Diagnosis"]), ("Age", facts["Age"])])

            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
            st.markdown("#### Rule checks")
            sections = {s["chunk_id"]: s for s in (ev.get("policy") or {}).get("sections", [])}
            for i, rule in enumerate(ev.get("rules", []), 1):
                passed = rule.get("result") == "PASS"
                basis = BASIS_LABEL.get(rule.get("basis"), rule.get("basis") or "")
                with st.container(border=True):
                    st.markdown(f"{pill(passed)} &nbsp; <b>Rule {i}: {esc(friendly_rule(rule.get('rule')))}</b>"
                                f" &nbsp; {chip(basis)}", unsafe_allow_html=True)
                    cites = rule_citations(rule)
                    if cites:
                        with st.expander("Policy text this rule is based on"):
                            for cid in cites:
                                sec = sections.get(cid)
                                if sec:
                                    st.markdown(f"**{sec['section']}**")
                                    st.write(sec["text"])
                                st.caption(cid)
                    elif rule.get("basis") == "team_assumption":
                        st.caption("Not stated in any policy.")

            st.caption("This assessment supports staff review. Only the insurer approves or denies.")
            with st.expander("Technical details (JSON)"):
                st.json(ev)
        else:
            card("<p style='margin:0'>Click <b>Run assessment</b> to check the selected claim against the policy rules.</p>")

# ===== TAB 4: SUMMARY =====
with tab4:
    stepper(3, progress())
    section_title("✅", "Summary", "What happens with this request")
    ev = current_evaluation()
    if not ev:
        st.info("👈 Select a claim in the sidebar, then click **Run assessment** in the Assessment tab")
    else:
        label, color, icon = decision_style(ev)
        r_icon, r_text = routing_parts(ev.get("routing"))
        facts = claim_facts(ev["claim_id"])
        policy = ev.get("policy") or {}
        admin = ev.get("admin") or {}

        meta = " · ".join(esc(x) for x in [f"Patient {ev.get('patient_id', '')}",
                                           f"Procedure {facts.get('Procedure', ev.get('procedure_code', ''))}",
                                           facts.get("Payer", ev.get("payer", "")), facts.get("State", "")] if x)
        card(f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px'>"
             f"<div><div style='font-size:1.35rem;font-weight:700;color:{NAVY}'>Claim {esc(ev['claim_id'])}</div>"
             f"<div class='pa-muted'>{meta}</div></div>"
             f"<div>{badge(f'{icon}  {label}', color)}</div></div>",
             title="Request")

        card(f"<div style='font-size:1.1rem'>{r_icon}&nbsp; {esc(r_text)}</div>", title="Next step")

        st.markdown("#### Request details")
        items = []
        for title, key in [("Billing code", "billing_code"), ("Authorization duration", "auth_duration"),
                           ("Follow-up plan", "follow_up_plan")]:
            value, basis = admin_value(admin.get(key))
            items.append((title, value, chip(basis) if basis else ""))
        kpi_row(items)

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        if policy.get("found"):
            card(f"<code>{esc(policy.get('policy_id'))}</code> &nbsp; "
                 f"{chip('Synthetic policy') if policy.get('synthetic') else ''}"
                 f"{chip('Region: ' + str(policy.get('jurisdiction') or 'national'))}",
                 title="Policy used")
        else:
            card(f"<p style='margin:0'>{esc(policy.get('message') or 'No policy found. Route to human review.')}</p>",
                 title="Policy used")

        try:
            pdf_bytes = build_assessment_pdf(ev, facts)
            st.download_button("📄  Download report (PDF)", data=pdf_bytes,
                               file_name=f"PriorAuth_Assessment_{ev.get('claim_id')}.pdf",
                               mime="application/pdf", type="primary")
        except Exception as e:
            st.error(f"Could not create the PDF report: {e}")

# ---------------------------------------------------------------- footer
st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
st.markdown(f"""
<div style="text-align:center;color:{GREY};font-size:0.85rem;line-height:1.7;border-top:1px solid #DCE7E5;padding-top:16px">
    <b>PriorAuthPilot</b> · Prior authorization assessment assistant<br>
    Synthetic data and policies, for demonstration only. Not for clinical or billing use.<br>
    Assessments support staff review; only the insurer approves or denies.<br>
    © 2026 PriorAuthPilot team ·
    <a href="https://github.com/nancytaswala23/priorauth-pilot" style="color:{TEAL};text-decoration:none">GitHub</a>
</div>""", unsafe_allow_html=True)