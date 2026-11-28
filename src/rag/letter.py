"""
Prior authorization letter drafting + checks (owner: Yashasvi).

Follows the Day 1 letter format: 7 fixed sections, facts only from the claim and the
cited policy sections, automated checks on every letter.

    from letter import draft_letter, check_letter
    letter = draft_letter(assessment, claim=claim_record)       # template, or LLM if enabled
    checks = check_letter(letter, assessment, claim=claim_record)

LLM is optional (default: none -> template letter). Set LLM_PROVIDER to one of:
    groq     needs GROQ_API_KEY    (model: GROQ_MODEL,   default openai/gpt-oss-120b)
    gemini   needs GEMINI_API_KEY  (model: GEMINI_MODEL, default gemini-2.0-flash)
    ollama   local, no key         (model: OLLAMA_MODEL, default llama3.1:8b)
Keys can also be put in a .env file in the repo root (never commit it).
If the LLM is unavailable or its letter fails any check, the template letter is used.

Command line (for testing):
    python src/rag/letter.py sample            # draft + check a built-in sample assessment
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date

SECTIONS = ["header", "request", "clinical_summary", "medical_necessity",
            "documentation_enclosed", "follow_up_plan", "signature"]
SECTION_TITLES = {
    "header": "Header", "request": "Request", "clinical_summary": "Clinical summary",
    "medical_necessity": "Medical necessity", "documentation_enclosed": "Documentation enclosed",
    "follow_up_plan": "Follow-up plan", "signature": "Signature",
}
FOOTER = "Synthetic draft for staff review. The insurer makes the final decision."
DRAFT_FOR = {"MEETS_CRITERIA", "NEEDS_DOCS"}

PROCEDURE_NAMES = {
    "72148": "lumbar spine MRI without contrast", "72149": "lumbar spine MRI with contrast",
    "72158": "lumbar spine MRI without and with contrast", "72141": "cervical spine MRI without contrast",
    "73721": "knee MRI without contrast", "70551": "brain MRI without contrast",
    "70553": "brain MRI without and with contrast", "62323": "lumbar epidural steroid injection (interlaminar)",
    "64483": "lumbar epidural steroid injection (transforaminal)", "27447": "total knee arthroplasty",
    "95806": "home sleep apnea test", "G0399": "home sleep apnea test", "95810": "attended sleep study",
    "95811": "attended sleep study with CPAP titration", "E0601": "CPAP device",
}


# ---------------------------------------------------------------- helpers
def _admin_value(item):
    if isinstance(item, dict):
        return item.get("value"), item.get("basis")
    return item, None


def _citations(rule):
    cites = []
    for key, value in rule.items():
        if key.endswith("cites_chunk") and value:
            cites += value if isinstance(value, list) else [value]
    return cites


def _friendly_rule(rule_text):
    r = (rule_text or "").lower()
    if "conservative_treatment_weeks" in r:
        return "at least the required weeks of conservative treatment, or a red flag"
    if "diagnosis" in r:
        return "a qualifying diagnosis, or a red flag"
    if "age" in r:
        return "patient is 18 or older"
    return rule_text or "policy criterion"


def _sections_by_id(assessment):
    policy = assessment.get("policy") or {}
    return {s.get("chunk_id"): s for s in policy.get("sections", [])}


def _documentation_text(assessment):
    for cid, sec in _sections_by_id(assessment).items():
        if cid and cid.endswith("::documentation_requirements"):
            return sec.get("text", ""), cid
    return "", None


# ---------------------------------------------------------------- template letter
def template_letter(assessment, claim=None):
    claim = claim or {}
    admin = assessment.get("admin") or {}
    code = str(assessment.get("procedure_code") or claim.get("procedure_code") or "")
    name = PROCEDURE_NAMES.get(code, "requested procedure")
    pos, _ = _admin_value(admin.get("place_of_service") or claim.get("place_of_service"))
    pos = str(pos).replace("_", " ") if pos else pos
    duration, d_basis = _admin_value(admin.get("auth_duration"))
    follow, f_basis = _admin_value(admin.get("follow_up_plan"))
    sections_by_id = _sections_by_id(assessment)

    passing, missing = [], []
    for rule in assessment.get("rules", []):
        if rule.get("basis") == "team_assumption":
            continue
        cites = _citations(rule)
        if rule.get("result") == "PASS":
            names = [sections_by_id[c]["section"] if c in sections_by_id else c.split("::")[-1].replace("_", " ")
                     for c in cites]
            passing.append((rule, cites, names))
        elif rule.get("result") == "MISSING":
            missing.append(rule)

    weeks = claim.get("conservative_treatment_weeks")
    red_flag = claim.get("red_flag_present")
    red_flag_text = ("a red flag is documented" if str(red_flag).strip().lower() in ("true", "1")
                     else "no red flag is documented") if red_flag is not None else "red flag status not documented"

    med_lines = [f"- Meets the policy criterion: {_friendly_rule(r.get('rule'))} "
                 f"(policy section: {', '.join(n) or 'cited section'})." for r, _, n in passing]
    if missing:
        med_lines.append("- Documentation is still needed for: "
                         + "; ".join(_friendly_rule(r.get("rule")) for r in missing) + ".")

    doc_text, doc_cid = _documentation_text(assessment)
    cited = sorted({c for _, cites, _ in passing for c in cites} | ({doc_cid} if doc_cid else set()))

    letter = {
        "header": (f"Date: {date.today():%B %d, %Y}\nTo: {assessment.get('payer') or claim.get('insurance') or 'Payer'} "
                   f"prior authorization review\nPatient ID: {assessment.get('patient_id') or claim.get('patient_id', '')}\n"
                   f"Claim ID: {assessment.get('claim_id', '')}\nFrom: [Ordering provider name, NPI]"),
        "request": (f"Requesting prior authorization for procedure code {code} ({name}).\n"
                    f"Place of service: {pos or 'not documented'}.\n"
                    f"Requested authorization duration: {duration or 'not documented'}"
                    + (" (team assumption)" if d_basis == "team_assumption" else "") + "."),
        "clinical_summary": (f"Diagnosis code: {claim.get('diagnosis_code') or 'not documented'}. "
                             f"Conservative treatment: {weeks if weeks is not None else 'not documented'} weeks. "
                             f"Red flags: {red_flag_text}."),
        "medical_necessity": "\n".join(med_lines) or "No policy criteria were met.",
        "documentation_enclosed": (f"Per the payer's documentation requirements: {doc_text}" if doc_text
                                   else "Clinical notes supporting the criteria above."),
        "follow_up_plan": (f"{follow}" + (" (team assumption)" if f_basis == "team_assumption" else "")) if follow
                          else "Not documented.",
        "signature": f"[Ordering provider signature]\n\n{FOOTER}",
    }
    return {"source": "template", "sections": letter, "cited_chunks": cited}


# ---------------------------------------------------------------- optional LLM
def _load_dotenv():
    """Read KEY=VALUE lines from .env in the repo root (no extra dependency)."""
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
    if os.path.exists(env):
        for line in open(env, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _prompt(assessment, base_letter):
    sections_by_id = _sections_by_id(assessment)
    cited_text = "\n\n".join(f"[{cid}] {sections_by_id[cid]['text']}" for cid in base_letter["cited_chunks"]
                              if cid in sections_by_id)
    return (
        "You write prior authorization request letters for staff review. Use ONLY the facts below. "
        "Do not add any clinical details, numbers, dates or codes that are not in the facts. "
        "Keep every '(team assumption)' label, keep the policy section names in the medical necessity "
        "section, and copy the documentation requirements in full. "
        "Never say the request is approved or denied. Return JSON with exactly these keys: "
        + ", ".join(SECTIONS) + ". Keep each section short and professional.\n\n"
        f"FACTS (from the claim and assessment):\n{json.dumps(base_letter['sections'], indent=2)}\n\n"
        f"POLICY TEXT THAT MAY BE CITED:\n{cited_text}\n"
    )


def _post_json(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "PriorAuthPilot/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None


def _call_llm(provider, prompt):
    """Return (model_name, parsed JSON dict) from the chosen provider."""
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY not set")
        model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        out = _post_json("https://api.groq.com/openai/v1/chat/completions",
                         {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                          "messages": [{"role": "user", "content": prompt}]},
                         {"Authorization": f"Bearer {key}"})
        return model, json.loads(out["choices"][0]["message"]["content"])
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")
        model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        out = _post_json(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                         {"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}},
                         {"x-goog-api-key": key})
        return model, json.loads(out["candidates"][0]["content"]["parts"][0]["text"])
    if provider == "ollama":
        model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
        out = _post_json(url, {"model": model, "prompt": prompt, "stream": False, "format": "json",
                               "options": {"temperature": 0}}, {})
        return model, json.loads(out["response"])
    raise RuntimeError(f"unknown LLM_PROVIDER '{provider}'")


def _llm_letter(provider, assessment, base_letter):
    model, out = _call_llm(provider, _prompt(assessment, base_letter))
    sections = {k: str(out.get(k, "")).strip() for k in SECTIONS}
    if FOOTER not in sections["signature"]:
        sections["signature"] = (sections["signature"] + "\n\n" + FOOTER).strip()
    return {"source": f"{provider}:{model}", "sections": sections, "cited_chunks": base_letter["cited_chunks"]}


# ---------------------------------------------------------------- public API
def draft_letter(assessment, claim=None, provider=None):
    """Return {source, sections, cited_chunks, checks} or None when no letter should be drafted."""
    if assessment.get("decision") not in DRAFT_FOR:
        return None
    base = template_letter(assessment, claim)
    base["checks"] = check_letter(base, assessment, claim)
    _load_dotenv()
    provider = (provider or os.environ.get("LLM_PROVIDER", "none")).lower()
    if provider in ("groq", "gemini", "ollama"):
        try:
            llm = _llm_letter(provider, assessment, base)
            llm["checks"] = check_letter(llm, assessment, claim)
            if llm["checks"]["all_passed"]:
                return llm
            failed = [k for k, v in llm["checks"].items() if v is False and k != "all_passed"]
            base["note"] = f"{provider} letter failed checks ({', '.join(failed)}); using the template letter."
            base["rejected_llm_letter"] = llm
        except Exception as e:  # no key, no network, rate limit, bad output
            base["note"] = f"{provider} unavailable ({type(e).__name__}: {str(e)[:80]}); using the template letter."
    return base


def _numbers(text):
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def _assumptions_labeled(s, admin):
    """Every admin value whose basis is team_assumption must say so in the letter."""
    ok = True
    for key, section in (("auth_duration", "request"), ("follow_up_plan", "follow_up_plan")):
        _, basis = _admin_value(admin.get(key))
        if basis == "team_assumption":
            ok = ok and "team assumption" in s.get(section, "").lower()
    return ok


def _sections_cited(s, letter, assessment):
    """The medical necessity section must name the policy section(s) it relies on."""
    by_id = _sections_by_id(assessment)
    names = {by_id[c]["section"].lower() for c in letter.get("cited_chunks", [])
             if c in by_id and not c.endswith("::documentation_requirements")}
    text = s.get("medical_necessity", "").lower()
    return all(n in text for n in names) if names else True


def _documentation_complete(s, assessment):
    """The policy's documentation requirements must appear in full, not shortened."""
    doc_text, _ = _documentation_text(assessment)
    if not doc_text:
        return True
    norm = lambda t: re.sub(r"\s+", " ", t).strip().lower().rstrip(".")
    return norm(doc_text) in norm(s.get("documentation_enclosed", ""))


def check_letter(letter, assessment, claim=None):
    claim = claim or {}
    s = letter["sections"]
    admin = assessment.get("admin") or {}
    code = str(assessment.get("procedure_code") or claim.get("procedure_code") or "")
    retrieved = set(_sections_by_id(assessment))
    full_text = "\n".join(s.get(k, "") for k in SECTIONS)

    # every number in the letter must come from the input (claim, assessment, cited policy text, today's date)
    allowed = _numbers(json.dumps(claim, default=str)) | _numbers(json.dumps(assessment, default=str)) \
        | _numbers(f"{date.today():%B %d, %Y}")
    invented = sorted(_numbers(full_text) - allowed)

    checks = {
        "billing_code_present": bool(code) and code in s.get("request", ""),
        "place_of_service_present": "not documented" not in s.get("request", "").lower().split("place of service")[-1][:40]
                                     and "place of service" in s.get("request", "").lower(),
        "auth_duration_present": "authorization duration" in s.get("request", "").lower()
                                 and "duration: not documented" not in s.get("request", "").lower(),
        "follow_up_present": bool(s.get("follow_up_plan")) and s["follow_up_plan"].lower() != "not documented.",
        "citations_valid": all(c in retrieved for c in letter.get("cited_chunks", [])),
        "no_invented_numbers": not invented,
        "no_decision_language": not re.search(r"\b(approved|denied|approve|deny)\b", full_text, re.I),
        "assumptions_labeled": _assumptions_labeled(s, admin),
        "policy_sections_cited": _sections_cited(s, letter, assessment),
        "documentation_complete": _documentation_complete(s, assessment),
    }
    checks["all_passed"] = all(checks.values())
    if invented:
        checks["invented_numbers"] = invented
    return checks


def letter_to_text(letter):
    return "\n\n".join(f"{SECTION_TITLES[k].upper()}\n{letter['sections'].get(k, '')}" for k in SECTIONS)


# ---------------------------------------------------------------- sample for testing
SAMPLE_ASSESSMENT = {
    "claim_id": "C_SAMPLE", "patient_id": "P_SAMPLE", "procedure_code": "72148", "payer": "SampleCommercial",
    "decision": "MEETS_CRITERIA", "decision_reason": "All policy criteria met.", "routing": "READY_TO_SUBMIT",
    "rules": [
        {"rule": "conservative_treatment_weeks >= 6 or red_flag_present", "basis": "policy", "result": "PASS",
         "samplecommercial_cites_chunk": ["commercial_lumbar_mri::medical_necessity_criteria"]},
        {"rule": "patient_age >= 18", "basis": "team_assumption", "result": "PASS"},
    ],
    "admin": {"billing_code": "72148", "place_of_service": "outpatient_imaging",
              "auth_duration": {"value": "60 days", "basis": "team_assumption"},
              "follow_up_plan": {"value": "Review results with the patient and update the treatment plan",
                                 "basis": "team_assumption"}},
    "policy": {"found": True, "policy_id": "commercial_lumbar_mri", "sections": [
        {"chunk_id": "commercial_lumbar_mri::medical_necessity_criteria", "section": "Medical Necessity Criteria",
         "text": "Lumbar spine MRI is medically necessary after at least 6 weeks of conservative treatment..."},
        {"chunk_id": "commercial_lumbar_mri::documentation_requirements", "section": "Documentation Requirements",
         "text": "Submit clinical notes from the last 60 days documenting symptom onset and duration, exam findings, "
                 "type and dates of conservative treatment and the member's response, and any red flag findings."},
    ]},
}
SAMPLE_CLAIM = {"patient_id": "P_SAMPLE", "procedure_code": "72148", "diagnosis_code": "M54.16",
                "conservative_treatment_weeks": 8, "red_flag_present": False, "insurance": "SampleCommercial"}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sample":
        out = draft_letter(SAMPLE_ASSESSMENT, SAMPLE_CLAIM)
        print(f"Source: {out['source']}" + (f"  ({out['note']})" if out.get("note") else ""))
        print("\n" + letter_to_text(out))
        print("\nChecks:")
        for k, v in out["checks"].items():
            print(f"  {k}: {v}")
    else:
        print(__doc__)
