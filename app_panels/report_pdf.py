"""
PDF report for one prior authorization assessment (PriorAuthPilot).

    from app_panels.report_pdf import build_assessment_pdf
    pdf_bytes = build_assessment_pdf(evaluation, facts)
    st.download_button("Download report (PDF)", pdf_bytes, file_name="report.pdf", mime="application/pdf")

Needs: pip install reportlab
"""

import textwrap
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TEAL = colors.HexColor("#0E9F8E")
NAVY = colors.HexColor("#0B3C49")
GREY = colors.HexColor("#5B6C75")
LIGHT = colors.HexColor("#EAF4F3")
LINE = colors.HexColor("#B8C4C9")

DECISIONS = {
    "MEETS_CRITERIA": ("Meets criteria", colors.HexColor("#0E9F8E")),
    "NEEDS_DOCS": ("Needs documentation", colors.HexColor("#C7801A")),
    "DOES_NOT_MEET_CRITERIA": ("Does not meet criteria", colors.HexColor("#E4572E")),
}
ROUTING = {
    "READY_TO_SUBMIT": "Ready to submit to the insurer. The insurer makes the final decision.",
    "REQUEST_DOCUMENTATION": "Request the missing information from the provider, then run the assessment again.",
    "HUMAN_REVIEW": "Send to a staff member for review before anything is submitted.",
}
BASIS = {
    "policy": "Policy",
    "policy_with_code_translation": "Policy (code mapping)",
    "team_assumption": "Team assumption",
}
DISCLAIMER = ("Synthetic data and policies, for demonstration only. Not for clinical or billing use. "
              "This assessment supports staff review; only the insurer approves or denies.")


def _clean(text):
    """The built-in PDF fonts cannot draw some symbols, so swap them for plain text."""
    text = "" if text is None else str(text)
    for a, b in {"≥": ">=", "≤": "<=", "→": "->", "·": "-", "—": "-", "–": "-",
                 "“": '"', "”": '"', "’": "'", "✅": "", "❌": "", "⚠️": "", "📄": "", "👤": ""}.items():
        text = text.replace(a, b)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")).strip()


def _friendly_rule(rule_text):
    r = (rule_text or "").lower()
    if "conservative_treatment_weeks" in r:
        return "At least 6 weeks of conservative treatment, or a red flag"
    if "diagnosis" in r:
        return "Qualifying diagnosis (radiculopathy), or a red flag"
    if "age" in r:
        return "Patient is 18 or older"
    return rule_text or "Rule"


def _citations(rule):
    cites = []
    for key, value in rule.items():
        if key.endswith("cites_chunk") and value:
            cites += value if isinstance(value, list) else [value]
    return cites


def _admin(item):
    if isinstance(item, dict):
        value = item.get("value") or "N/A"
        basis = item.get("basis")
        return f"{value} ({basis.replace('_', ' ')})" if basis else str(value)
    return str(item) if item not in (None, "") else "N/A"


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    lines = textwrap.wrap(DISCLAIMER, 115)
    for i, line in enumerate(lines[:2]):
        canvas.drawString(doc.leftMargin, (0.5 - 0.13 * i) * inch, line)
    canvas.drawRightString(letter[0] - doc.rightMargin, 0.37 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build_assessment_pdf(evaluation, facts=None):
    """Return the PDF report as bytes. `facts` is the optional dict from claim_facts() in app.py."""
    ev = evaluation or {}
    facts = facts or {}
    policy = ev.get("policy") or {}
    admin = ev.get("admin") or {}
    sections = {s.get("chunk_id"): s for s in policy.get("sections", [])}

    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica", fontSize=10, leading=14, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11, textColor=GREY)
    h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=NAVY)
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=NAVY,
                        spaceBefore=14, spaceAfter=6)
    brand = ParagraphStyle("brand", parent=body, fontName="Helvetica-Bold", fontSize=10, textColor=TEAL)
    cell = ParagraphStyle("cell", parent=body, fontSize=9.5, leading=12.5)
    cell_b = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)

    def table(rows, widths, header=True):
        t = Table(rows, colWidths=widths, hAlign="LEFT")
        style = [("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                 ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), NAVY)]
            style += [("BACKGROUND", (0, i), (-1, i), LIGHT) for i in range(2, len(rows), 2)]
        t.setStyle(TableStyle(style))
        return t

    story = []
    width = letter[0] - 1.5 * inch

    # Header
    story += [Paragraph("PriorAuthPilot", brand),
              Paragraph("Prior Authorization Assessment Report", h1),
              Paragraph(_clean(f"Claim {ev.get('claim_id', '')} - generated {datetime.now():%B %d, %Y %H:%M}"), small),
              Spacer(1, 12)]

    # Result box
    label, color = DECISIONS.get(ev.get("decision"), (ev.get("decision") or "Unknown", GREY))
    routing = ROUTING.get(str(ev.get("routing") or "").upper(), str(ev.get("routing") or "-"))
    result = Table([
        [Paragraph(f"<font color='white'><b>{_clean(label)}</b></font>", ParagraphStyle("r", parent=body, fontSize=14, leading=18))],
        [Paragraph(f"<b>Why:</b> {_clean(ev.get('decision_reason') or '-')}", body)],
        [Paragraph(f"<b>Next step:</b> {_clean(routing)}", body)],
    ], colWidths=[width], hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), color), ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10)]))
    story.append(result)

    # Claim details
    story.append(Paragraph("Claim details", h2))
    details = [
        ("Claim ID", ev.get("claim_id")), ("Patient ID", ev.get("patient_id")),
        ("Procedure code", facts.get("Procedure", ev.get("procedure_code"))), ("Diagnosis code", facts.get("Diagnosis")),
        ("Payer", facts.get("Payer", ev.get("payer"))), ("State", facts.get("State")),
        ("Age", facts.get("Age")), ("Conservative treatment", facts.get("Treatment")),
        ("Red flag present", facts.get("Red flag")),
    ]
    details = [(k, v) for k, v in details if v not in (None, "")]
    rows = []
    for i in range(0, len(details), 2):
        pair = details[i:i + 2] + [("", "")] * (2 - len(details[i:i + 2]))
        rows.append([Paragraph(_clean(pair[0][0]), cell_b), Paragraph(_clean(pair[0][1]), cell),
                     Paragraph(_clean(pair[1][0]), cell_b), Paragraph(_clean(pair[1][1]), cell)])
    if rows:
        story.append(table(rows, [1.45 * inch, 2.05 * inch, 1.45 * inch, 2.05 * inch], header=False))

    # Rule checks
    story.append(Paragraph("Rule checks", h2))
    rows = [[Paragraph("Result", head), Paragraph("Rule", head), Paragraph("Basis", head), Paragraph("Policy sections", head)]]
    for rule in ev.get("rules", []):
        passed = rule.get("result") == "PASS"
        cites = _citations(rule)
        cited = ", ".join(sections[c]["section"] if c in sections else c.split("::")[-1].replace("_", " ") for c in cites)
        if not cited and rule.get("basis") == "team_assumption":
            cited = "Not stated in any policy"
        rows.append([
            Paragraph(f"<font color='{'#0E9F8E' if passed else '#E4572E'}'><b>{'PASS' if passed else 'FAIL'}</b></font>", cell),
            Paragraph(_clean(_friendly_rule(rule.get("rule"))), cell),
            Paragraph(_clean(BASIS.get(rule.get("basis"), rule.get("basis") or "-")), cell),
            Paragraph(_clean(cited or "-"), cell),
        ])
    story.append(table(rows, [0.7 * inch, 2.75 * inch, 1.35 * inch, 2.2 * inch]))

    # Request details (administrative elements)
    story.append(Paragraph("Request details", h2))
    rows = [[Paragraph("Billing code", head), Paragraph("Authorization duration", head), Paragraph("Follow-up plan", head)],
            [Paragraph(_clean(_admin(admin.get("billing_code"))), cell),
             Paragraph(_clean(_admin(admin.get("auth_duration"))), cell),
             Paragraph(_clean(_admin(admin.get("follow_up_plan"))), cell)]]
    story.append(table(rows, [2.0 * inch, 2.5 * inch, 2.5 * inch]))

    # Policy used
    story.append(Paragraph("Policy used", h2))
    if policy.get("found"):
        region = policy.get("jurisdiction") or "national"
        synthetic = " (synthetic policy)" if policy.get("synthetic") else ""
        story.append(Paragraph(_clean(f"{policy.get('policy_id')}{synthetic} - region: {region}"), body))
        cited_ids = [c for r in ev.get("rules", []) for c in _citations(r)]
        shown = [sections[c] for c in dict.fromkeys(cited_ids) if c in sections]
        for sec in shown:
            story.append(KeepTogether([Spacer(1, 6), Paragraph(f"<b>{_clean(sec.get('section'))}</b>", body),
                                       Paragraph(_clean(sec.get("text")), small)]))
    else:
        story.append(Paragraph(_clean(policy.get("message") or "No policy found. Route to human review."), body))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.85 * inch,
                            title=f"Assessment report {ev.get('claim_id', '')}", author="PriorAuthPilot")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()