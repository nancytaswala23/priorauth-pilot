# MCP Server Architecture

## Overview

PriorAuthPilot's orchestrating agent (built with LangGraph) never talks to a
backing data system directly. Instead, it calls three separate MCP (Model
Context Protocol) tool servers, each wrapping one genuinely separate
real-world system. This is a deliberate choice, not extra complexity for its
own sake: a hospital's claims data, a payer's policy library, and a
submission/tracking system really are three separate systems run by
different parties in the real world, so the architecture models that
directly instead of bundling everything behind one API.

## Server 1 — Claims & Patient Data

- **Backed by:** Snowflake (`src/data_pipeline/snowflake_schema.sql`)
- **Tables queried:** `PATIENTS`, `CLAIMS`
- **What it does:** given a `patient_id`, returns demographics (age, gender,
  state) and claim history (diagnosis code(s), procedure code, date of
  service)
- **Endpoints:**
  - `get_patient(patient_id)` → demographics (age, gender, state)
  - `get_claims(patient_id)` → claim history (diagnosis codes, procedure code, date of service)
  - `get_conservative_treatment(patient_id)` → weeks of documented conservative treatment
- **Called during:** Step 1 (Ingest Case) and Step 3 (Evaluate Criteria, for
  any rule whose `source` is `CLAIMS` or `PATIENTS`)

## Server 2 — Policy Knowledge (RAG)

- **Backed by:** `src/rag/rag_pipeline.py` — a FAISS vector database,
  chunked by section and embedded with `all-MiniLM-L6-v2`, searched with
  payer/procedure metadata filters applied before semantic search runs.
- **All policy content is synthetic (`synthetic: true` on every document).**
  This is a deliberate scoping decision, not an oversight: the CPT procedure
  codes embedded in real Medicare LCD/NCD documents *and* real private payer
  bulletins (e.g. Aetna's Clinical Policy Bulletins) are licensed by the AMA
  for personal viewing only — not for the copying, derivative use, and
  redistribution a public RAG pipeline and GitHub repo would involve. We use
  real payer pages only as a structural reference, and write every policy
  ourselves in plain language for Medicare and for a clearly fictional payer
  ("SampleCommercial").
- **Standardized chunk schema** every retrieved result follows (verified
  directly against `src/rag/rag_pipeline.py`'s `build_chunks()`): `chunk_id`,
  `policy_id`, `payer`, `document_type` (`LCD` / `Commercial clinical policy
  bulletin`), `procedure_codes` (a list — some policies cover more than one
  code), `jurisdiction`, `synthetic`, `section`, `text`, `source_file`.
  **Section headings are NOT one universal set** — each payer/document type
  defines its own real headings in `config/chunking_strategy.yaml`: Medicare
  LCDs use "Coverage Indications, Limitations, and/or Medical Necessity",
  "Red Flag Conditions", "Limitations", "Documentation Requirements";
  SampleCommercial bulletins use a different 6-heading layout entirely
  ("Precertification Requirements", "Medical Necessity Criteria", etc.).
  `criteria_rules.yaml` cites the exact `chunk_id`, not a generic heading
  name, which is what actually lets a rule survive this per-payer
  difference.
- **Retrieval follows a hierarchy**, matching how real Medicare coverage
  policy actually works: national (NCD) first, falling back to regional
  (LCD, jurisdiction-specific) if the national policy doesn't fully settle
  the question. A private-payer case skips straight to that payer's own
  policy — there is no national/regional step for a non-Medicare payer. See
  `AgentState.national_policy` / `.regional_policy` / `.payer_policy` /
  `.applicable_policy` in `src/agent/agent_state.py`.
- **Endpoints:**
  - `search_policy(payer, procedure_code, jurisdiction, query)` → ranked policy chunks (each with `chunk_id`, `section`, `text`), metadata-filtered before semantic search
  - `get_policy_metadata(policy_id)` → the full standardized record (payer, document_type, jurisdiction, procedure_codes, synthetic)
- **Called during:** Step 2 (Retrieve Policy), and again during Step 7 if an
  appeal needs to cite policy language directly.

## Server 3 — Submission & Tracking

- **Backed by:** a simulated submission log. No real payer API access is
  available for a student project, so this step is modeled rather than
  live — though we identified that ONC's public Inferno reference server
  implements the actual Da Vinci PAS standard CMS-0057-F mandates, and this
  simulated server is designed to mirror that same request/response shape
  as a possible stretch goal.
- **What it does:** accepts a decision (`APPROVED` / `NEEDS_DOCS` /
  `DENIED`), logs and tracks it, and on denial returns the specific X12
  CARC/RARC reason code.
- **Endpoints:**
  - `submit_approval(request_id)` → logs an approval
  - `submit_denial(request_id, reason_code)` → logs a denial with its X12 CARC/RARC code
  - `track_status(request_id)` → current status of a previously submitted request
- **Called during:** Step 5 (Act), Step 6 (Track Status), and Step 7
  (Appeal, to read the denial reason).

## How the agent ties these together

**Concrete example:** a case arrives for Patient P001, lumbar MRI (72148), Medicare. The agent calls Server 1 for P001's claim history, Server 2 for the applicable NCD/LCD, evaluates `config/criteria_rules.yaml` against both, and either approves, requests documentation, or denies — logging the outcome through Server 3.

| Step | Action | Server called |
|---|---|---|
| 1. Ingest Case | Pull patient + claim history | Server 1 |
| 2. Retrieve Policy | Pull national, then regional (or payer-specific) policy | Server 2 |
| 3. Evaluate Criteria | Check `AgentState` against `config/criteria_rules.yaml`, tracing each rule back to its `source` table and its `cites_chunk` id | — (local logic) |
| 4. Decide & Route | Submit / request docs / escalate | — (local logic) |
| 5. Act | Submit the decision | Server 3 |
| 6. Track Status | Poll for an outcome | Server 3 |
| 7. On Denial | Read reason code, re-retrieve policy language, draft appeal | Server 3 → Server 2 |

Every node in the LangGraph graph reads from and writes to the same
`AgentState` object (`src/agent/agent_state.py`), so state flows cleanly
end to end:

**Patient data (Nancy) + Policies (Yashasvi) → Agent (Rekha) → Decision.**