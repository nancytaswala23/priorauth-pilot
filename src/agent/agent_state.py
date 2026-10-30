"""
AgentState — the shared state object that flows through PriorAuthPilot's
LangGraph orchestration loop.

Every node in the graph (ingest -> retrieve policy -> evaluate criteria ->
decide -> act -> track -> appeal) reads from and writes to this same object,
so each step only needs to know the fields it cares about rather than
passing a growing list of function arguments around.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PolicyReference:
    """One retrieved policy chunk, matching EXACTLY what
    src/rag/rag_pipeline.py's build_chunks()/search() actually returns
    (verified directly against Yashasvi's code, not assumed):

        {chunk_id, policy_id, payer, jurisdiction, document_type,
         procedure_codes, section, synthetic, source_file, text, score}

    `chunk_id` is the field criteria_rules.yaml's `cites_chunk` points at —
    her own code comment says it exists "so rules in criteria_rules.yaml can
    cite it." `section` headings are NOT a single universal set -- Medicare
    and SampleCommercial each use their own different real headings (see
    config/chunking_strategy.yaml); there is no fixed 5-heading schema.

    All policy content is currently synthetic (own-words, not real payer
    text) — see docs/mcp_design.md for why: the CPT procedure codes embedded
    in real Medicare LCD/NCD documents and real private payer bulletins are
    licensed by the AMA for personal viewing only, not for reuse in a
    pipeline whose repo may go public.
    """
    chunk_id: str
    policy_id: str
    payer: str
    document_type: str  # "LCD" | "Commercial clinical policy bulletin" (real values, not guessed)
    procedure_codes: List[str]  # a list -- some policies cover multiple codes
    jurisdiction: str
    synthetic: bool
    section: str
    text: str
    source_file: str
    score: Optional[float] = None  # retrieval relevance score from Yashasvi's search() -- always real when built from a live search
    effective_date: Optional[str] = None  # NOT currently produced by the real pipeline -- always None for now

    @property
    def source_level(self) -> str:
        """Derived from document_type rather than stored separately, so the
        two can never disagree with each other."""
        return {"NCD": "NATIONAL", "LCD": "REGIONAL"}.get(self.document_type, "PAYER_SPECIFIC")


@dataclass
class AgentState:
    # --- Set at ingest (Step 1), pulled from MCP Server #1: Claims & Patient Data ---
    patient_id: str
    diagnosis_codes: List[str]
    procedure_code: str
    payer: str
    jurisdiction: str

    # --- Set during policy retrieval (Step 2), from MCP Server #2: Policy Knowledge / RAG ---
    # Checked in this order, matching how Medicare coverage policy actually works:
    #   1. NATIONAL  — an NCD, same across the whole country (Medicare only)
    #   2. REGIONAL  — an LCD, specific to this jurisdiction (Medicare only)
    #   3. PAYER_SPECIFIC — a private payer's own policy bulletin
    # A Medicare case checks national, then falls back to regional if the
    # national policy doesn't fully settle it. A private-payer case skips
    # straight to payer_policy — there is no national/regional step for them.
    national_policy: Optional[PolicyReference] = None
    regional_policy: Optional[PolicyReference] = None
    payer_policy: Optional[PolicyReference] = None
    applicable_policy: Optional[PolicyReference] = None  # whichever one actually governs this case

    # --- Set after criteria evaluation (Step 3), checked against config/criteria_rules.yaml ---
    criteria_met: Optional[bool] = None

    # --- Set after the decide step (Step 4) ---
    # This is the AGENT's own assessment, not an adjudication -- the agent
    # cannot approve or deny a claim; only the insurer (Server 3) can.
    # MEETS_CRITERIA  -> safe to submit
    # NEEDS_DOCS      -> missing documentation before it can be submitted
    # DOES_NOT_MEET_CRITERIA -> likely to be denied if submitted as-is;
    #                           still routed to a human / submitted for the
    #                           insurer to actually decide, not auto-rejected
    decision: Optional[str] = None  # "MEETS_CRITERIA" | "NEEDS_DOCS" | "DOES_NOT_MEET_CRITERIA"

    # --- Set only after Server 3 (the simulated insurer) actually returns a
    # denial in response to a real or simulated submission (Step 7) ---
    denial_reason_code: Optional[str] = None  # X12 CARC code, e.g. "16" -- from the INSURER, not the agent
    appeal_draft: Optional[str] = None  # the drafted appeal text, grounded in denial_reason_code + applicable_policy

    # --- Optional: how confident the evaluation was, not just pass/fail ---
    confidence_score: Optional[float] = None  # compared against criteria_rules.yaml's approval_threshold