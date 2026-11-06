"""
Shared UI components for the PriorAuthPilot Streamlit app.
Card-based look (similar to a React dashboard) built with HTML/CSS inside Streamlit.

    from app_panels.ui import inject_css, section_title, card, kpi_row, badge, chip, stepper
"""

import html

import streamlit as st

NAVY = "#0B3C49"
TEAL = "#0E9F8E"
MINT = "#7FC8BF"
LIGHT = "#EAF4F3"
SOFT = "#F5FAF9"
GREY = "#5B6C75"
BORDER = "#DCE7E5"
AMBER = "#F2A541"
CORAL = "#E4572E"


def esc(text):
    return html.escape("" if text is None else str(text))


def inject_css():
    st.markdown(f"""
<style>
    .block-container {{padding-top: 1.6rem; max-width: 1200px;}}
    h1, h2, h3, h4 {{color: {NAVY};}}
    [data-testid="stToolbar"] {{display: none;}}
    footer {{visibility: hidden;}}

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {{gap: 8px; border-bottom: none;}}
    .stTabs [data-baseweb="tab"] {{background: {LIGHT}; border-radius: 12px; padding: 10px 22px; height: auto;}}
    .stTabs [data-baseweb="tab"] p {{font-weight: 600; color: {NAVY}; font-size: 0.98rem;}}
    .stTabs [aria-selected="true"] {{background: {NAVY} !important;}}
    .stTabs [aria-selected="true"] p {{color: #FFFFFF !important;}}
    .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{display: none;}}

    /* Native widgets */
    div[data-testid="stVerticalBlockBorderWrapper"] {{border-radius: 16px;}}
    .stButton > button, .stDownloadButton > button {{border-radius: 999px; padding: 0.5rem 1.5rem; font-weight: 600;}}
    [data-testid="stExpander"] details {{border-radius: 14px; border-color: {BORDER};}}
    [data-testid="stExpander"] summary p {{font-weight: 600; color: {NAVY};}}
    .stTextInput input {{border-radius: 12px;}}

    /* Custom components */
    .pa-card {{background: #FFFFFF; border: 1px solid {BORDER}; border-radius: 16px; padding: 18px 22px;
               box-shadow: 0 1px 4px rgba(11,60,73,0.06); margin-bottom: 14px;}}
    .pa-card-title {{font-size: 0.8rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
                     color: {GREY}; margin-bottom: 8px;}}
    .pa-kpi {{background: {SOFT}; border: 1px solid {BORDER}; border-radius: 14px; padding: 14px 16px; height: 100%;}}
    .pa-kpi-label {{font-size: 0.8rem; color: {GREY}; margin-bottom: 4px;}}
    .pa-kpi-value {{font-size: 1.35rem; font-weight: 700; color: {NAVY}; line-height: 1.2; word-break: break-word;}}
    .pa-kpi-sub {{margin-top: 6px;}}
    .pa-badge {{display: inline-block; color: #FFFFFF; padding: 6px 16px; border-radius: 999px; font-weight: 700;}}
    .pa-chip {{display: inline-block; background: {LIGHT}; color: {NAVY}; padding: 2px 10px; border-radius: 999px;
               font-size: 0.78rem; font-weight: 600; margin-right: 6px;}}
    .pa-pill-pass {{display: inline-block; background: #DDF3EF; color: {TEAL}; padding: 3px 12px; border-radius: 999px;
                    font-size: 0.8rem; font-weight: 700;}}
    .pa-pill-fail {{display: inline-block; background: #FBE3DC; color: {CORAL}; padding: 3px 12px; border-radius: 999px;
                    font-size: 0.8rem; font-weight: 700;}}
    .pa-section {{display: flex; align-items: center; gap: 14px; margin: 4px 0 16px 0;}}
    .pa-section-icon {{width: 46px; height: 46px; border-radius: 14px; background: {LIGHT}; display: flex;
                       align-items: center; justify-content: center; font-size: 1.4rem;}}
    .pa-section-title {{font-size: 1.45rem; font-weight: 700; color: {NAVY}; line-height: 1.2;}}
    .pa-section-sub {{font-size: 0.92rem; color: {GREY};}}
    .pa-stepper {{display: flex; gap: 8px; margin: 0 0 18px 0; flex-wrap: wrap;}}
    .pa-step {{flex: 1; min-width: 150px; display: flex; align-items: center; gap: 10px; padding: 10px 14px;
               border-radius: 12px; background: {SOFT}; border: 1px solid {BORDER}; color: {GREY}; font-weight: 600;}}
    .pa-step-num {{width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
                   background: {BORDER}; color: {NAVY}; font-size: 0.85rem; font-weight: 700;}}
    .pa-step.done {{background: #DDF3EF; border-color: #BFE6DF; color: {NAVY};}}
    .pa-step.done .pa-step-num {{background: {TEAL}; color: #FFFFFF;}}
    .pa-step.active {{background: {NAVY}; border-color: {NAVY}; color: #FFFFFF;}}
    .pa-step.active .pa-step-num {{background: #FFFFFF; color: {NAVY};}}
    .pa-muted {{color: {GREY}; font-size: 0.88rem;}}
</style>
""", unsafe_allow_html=True)


def badge(text, color):
    return f"<span class='pa-badge' style='background:{color}'>{esc(text)}</span>"


def chip(text):
    return f"<span class='pa-chip'>{esc(text)}</span>"


def pill(passed):
    return "<span class='pa-pill-pass'>PASS</span>" if passed else "<span class='pa-pill-fail'>FAIL</span>"


def section_title(icon, title, subtitle=""):
    st.markdown(f"""
<div class="pa-section">
  <div class="pa-section-icon">{icon}</div>
  <div><div class="pa-section-title">{esc(title)}</div>
       <div class="pa-section-sub">{esc(subtitle)}</div></div>
</div>""", unsafe_allow_html=True)


def card(body_html, title=None):
    """A white card. body_html is trusted HTML built by the app (escape user values with esc())."""
    head = f"<div class='pa-card-title'>{esc(title)}</div>" if title else ""
    st.markdown(f"<div class='pa-card'>{head}{body_html}</div>", unsafe_allow_html=True)


def kpi_row(items):
    """items: list of (label, value) or (label, value, sub_html)."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value = item[0], item[1]
        sub = f"<div class='pa-kpi-sub'>{item[2]}</div>" if len(item) > 2 and item[2] else ""
        col.markdown(f"<div class='pa-kpi'><div class='pa-kpi-label'>{esc(label)}</div>"
                     f"<div class='pa-kpi-value'>{esc(value)}</div>{sub}</div>", unsafe_allow_html=True)


def stepper(active, done):
    """active: index 0-3 of the current tab. done: list of 4 booleans."""
    names = ["Select claim", "Find policy", "Run assessment", "Review summary"]
    parts = []
    for i, name in enumerate(names):
        cls = "active" if i == active else ("done" if done[i] else "")
        mark = "✓" if done[i] and i != active else str(i + 1)
        parts.append(f"<div class='pa-step {cls}'><div class='pa-step-num'>{mark}</div>{name}</div>")
    st.markdown(f"<div class='pa-stepper'>{''.join(parts)}</div>", unsafe_allow_html=True)


def kv_card(title, rows, footer_html=""):
    """A card with label/value rows. rows: list of (label, value_html_or_text, is_html=False)."""
    lines = []
    for row in rows:
        label, value = row[0], row[1]
        is_html = len(row) > 2 and row[2]
        shown = value if is_html else esc(value if value not in (None, "") else "—")
        lines.append(
            f"<tr><td style='color:{GREY};padding:7px 12px 7px 0;width:44%;vertical-align:top'>{esc(label)}</td>"
            f"<td style='color:{NAVY};font-weight:600;padding:7px 0;vertical-align:top'>{shown}</td></tr>")
    foot = f"<div style='margin-top:10px'>{footer_html}</div>" if footer_html else ""
    card(f"<table style='width:100%;border-collapse:collapse;font-size:0.97rem'>{''.join(lines)}</table>{foot}",
         title=title)