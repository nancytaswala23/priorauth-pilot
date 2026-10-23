# PriorAuthPilot: Agentic AI for Healthcare Prior Authorization

 Nancy
## Overview
Automating healthcare prior authorization using agentic AI, retrieval-augmented generation (RAG), and deterministic rules to reduce processing time from 11-16 minutes to under 5 minutes.

## Problem
- **92%** of medical practices hire staff specifically for prior authorization (MGMA)
- **11-16 minutes** per request even when filed electronically (CAQH)
- Coverage criteria fragmented: NCDs (national), LCDs (regional), private payer policies (separate PDFs)

## Solution
7-step agentic loop:
1. Ingest case (diagnosis, procedure, payer, patient history)
2. Retrieve policy (LCD/NCD via RAG, filtered by payer + jurisdiction)
3. Evaluate criteria (deterministic rule checks)
4. Decide & route (submit / request docs / escalate)
5. Act (auto-submit or tell staff what's missing)
6. Track status (monitor approval/denial)
7. On denial (pull CARC/RARC code, draft grounded appeal)

## Tech Stack
| Component | Technology | Why |
|-----------|-----------|-----|
| Data Warehouse | Snowflake + dbt | Relational joins, transformations |
| Patient Data | Synthea FHIR | Industry standard healthcare format |
| Embeddings | all-MiniLM-L6-v2 | Fast, lightweight, sufficient quality |
| Vector DB | FAISS | Simple, free, fast prototyping |
| Policy Chunking | Semantic sections | Meaningful chunks, not random splits |
| Agent Orchestration | LangGraph | Workflow branching |
| Tool Integration | MCP Servers (3) | Modular, mirrors real-world separation |
| Rule Evaluation | Deterministic Python | Auditable, testable, explainable |
| Denial Codes | X12 CARC/RARC | Industry standard codes |

## Data Sources
- **Synthea FHIR**: Generates synthetic patient records in healthcare standard format
- **Medicare Coverage Database**: Free NCDs (National Coverage Determinations), updated weekly
- **Private Payer Policies**: Aetna, UnitedHealthcare, Cigna PDFs from provider portals
- **X12 CARC/RARC Codes**: Standard denial reason codes every insurer uses

## Project Structure
=======
## Executive Summary

PriorAuthPilot is an intelligent automation system that uses agentic AI, retrieval-augmented generation (RAG), and deterministic rules to streamline healthcare prior authorization (PA) requests. By combining patient data, insurance policies, and rule-based decision logic, it reduces processing time from **11-16 minutes to under 5 minutes** while improving accuracy and auditability.

---

## The Problem

### Healthcare Prior Authorization Crisis
- **92%** of medical practices hire or reassign staff specifically for prior authorization management (MGMA)
- **11-16 minutes** per request even when filed electronically (CAQH)
- Coverage criteria are **fragmented and constantly changing**:
  - National Coverage Determinations (NCDs) - Medicare-wide rules
  - Local Coverage Determinations (LCDs) - Regional variations by MAC
  - Private Payer Policies - Separate PDFs for Aetna, UnitedHealthcare, Cigna, etc.
- **No standardized access** - Staff must manually navigate different policy documents
- **Denials are common** - Lack of policy knowledge leads to improper submissions

### Why This Matters
Prior authorization is a critical bottleneck in healthcare delivery. Clinicians wait for approval, patient care is delayed, and administrative staff spend hours on repetitive work that machines can automate.

---

## The Solution

### 7-Step Agentic Loop

```
┌─────────────────────────────────────┐
│   1. INGEST CASE                    │
│   Read patient demographics,        │
│   diagnosis, procedure, payer       │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│   2. RETRIEVE POLICY (RAG)          │
│   Get actual coverage rules         │
│   filtered by payer & jurisdiction  │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│   3. EVALUATE CRITERIA              │
│   Check deterministic rules         │
│   (not AI guessing)                 │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│   4. DECIDE & ROUTE                 │
│   → APPROVED: Submit automatically  │
│   → NEEDS_DOCS: Request info        │
│   → DENIED: Escalate to human       │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│   5. ACT                            │
│   Execute decision (submit/request) │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│   6. TRACK STATUS                   │
│   Monitor approval/denial response  │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│   7. ON DENIAL                      │
│   Pull X12 reason code              │
│   Draft grounded appeal letter      │
└─────────────────────────────────────┘
```

---

## Technical Architecture

### System Components

```
┌────────────────────────────────────────────────┐
│         Orchestrating Agent (LangGraph)        │
│  Manages workflow, branching, decision-making  │
└─────┬──────────────────┬──────────────┬────────┘
      │                  │              │
  ┌───▼────┐        ┌────▼────┐    ┌───▼───┐
  │ MCP #1 │        │ MCP #2  │    │MCP #3 │
  │ Claims │        │ Policy  │    │Submit │
  │ Patient│        │Knowledge│    │Track  │
  │ Data   │        │  (RAG)  │    │       │
  └────────┘        └─────────┘    └───────┘
      ↓                  ↓              ↓
 ┌────────────┐   ┌──────────────┐ ┌──────────┐
 │ Snowflake  │   │ FAISS Vector │ │ Simulated│
 │ Database   │   │ Database     │ │ Payer API│
 └────────────┘   └──────────────┘ └──────────┘
```

### Data Flow

1. **Patient Data (Snowflake)**
   - Stored in normalized schema (PATIENTS, CLAIMS, POLICIES tables)
   - Transformed with dbt into analytics-ready format
   - Queried via MCP Server #1

2. **Insurance Policies (RAG)**
   - Downloaded from Medicare Coverage Database & payer websites
   - Chunked by semantic sections (Indications, Documentation, Coverage Criteria)
   - Embedded using all-MiniLM-L6-v2 (384-dimensional vectors)
   - Stored in FAISS for fast similarity search
   - Retrieved via MCP Server #2

3. **Deterministic Rules**
   - Hard YES/NO logic (not AI guessing)
   - Configured in YAML for clarity and auditability
   - Example: "conservative_treatment_weeks >= 6" (critical rule)

4. **Decision & Submission**
   - Agent evaluates criteria against retrieved policy
   - Decides: APPROVED / NEEDS_DOCS / DENIED
   - Submits via MCP Server #3 (simulated payer API)

---

## Technology Stack

| Layer | Technology | Purpose | Why This Choice |
|-------|-----------|---------|-----------------|
| **Data Warehouse** | Snowflake + dbt | Store and transform patient/claims data | Enterprise-grade, scalable, supports healthcare data |
| **Patient Data Format** | Synthea FHIR | Generate realistic synthetic patient records | Industry-standard healthcare format (HL7 FHIR) |
| **Embeddings** | all-MiniLM-L6-v2 (384-dim) | Convert policy text to vectors | Lightweight, fast, sufficient quality for medical text |
| **Vector Database** | FAISS | Store and retrieve policy embeddings | Simple, free, efficient similarity search |
| **Policy Chunking** | Semantic sections (YAML) | Split policies meaningfully | Preserves policy structure vs. random fixed-length chunks |
| **Agent Orchestration** | LangGraph | Manage workflow with branching logic | Handles complex agentic workflows |
| **Tool Integration** | MCP Servers (3 separate) | Modular access to claims, policies, submission | Mirrors real-world system separation |
| **Decision Logic** | Deterministic Python + YAML | Auditable, testable rule evaluation | Transparency & explainability critical for healthcare |
| **Denial Codes** | X12 CARC/RARC | Standard reason codes for denials | Industry standard (used by every insurer) |

---

## Data Sources

### 1. Patient & Claims Data
- **Synthea** (github.com/synthetichealth/synthea)
  - Generates synthetic FHIR patient records
  - Includes demographics, conditions, medications, procedures
  - 100% open source
  - Command: `./run_synthea -p 1000` (generates 1000 synthetic patients)

### 2. Insurance Policies
- **Medicare Coverage Database** (cms.gov/medicare-coverage-database)
  - Free National Coverage Determinations (NCDs)
  - Updated weekly
  - Covers ~300+ procedures
  
- **Private Payer Policies** (from provider websites)
  - Aetna, UnitedHealthcare, Cigna PDFs
  - Downloaded from provider portals
  - Includes coverage criteria, prior auth requirements

### 3. Denial Reason Codes
- **X12 CARC/RARC Codes** (x12.org)
  - Claim Adjustment Reason Codes (CARC)
  - Remittance Advice Remark Codes (RARC)
  - Examples: CARC 16 = "Claim lacks clinical detail", CARC 32 = "Patient ineligible"

### 4. Federal Compliance
- **CMS-0057-F / CMS-0062**
  - New federal rules requiring FHIR-based PA APIs by January 2027
  - PriorAuthPilot uses FHIR format and MCP pattern (similar to FHIR API concept)

---

## Project Structure

```
priorauth-pilot/
├── README.md                          # This file
├── 
├── data/
│   └── raw/policies/                  # Downloaded insurance policies
│       ├── medicare_ncd_sample.txt
│       └── aetna_sample.pdf
│
├── src/
│   ├── data_pipeline/
│   │   └── snowflake_schema.sql       # 3 tables: PATIENTS, CLAIMS, POLICIES
│   └── agent/
│       └── agent_state.py             # Agent state definition
│
├── dbt/
│   ├── dbt_project.yml                # dbt configuration
│   └── models/
│       └── fct_claims.sql             # Fact table for claims
│
├── config/
│   ├── chunking_strategy.yaml         # How to chunk policies
│   └── criteria_rules.yaml            # Deterministic approval rules
│
└── docs/
    ├── snowflake_schema.md            # Schema documentation
    ├── vector_db_choice.md            # RAG & vector DB design
    └── mcp_design.md                  # MCP server architecture
```

---

## Snowflake Schema

### PATIENTS Table
```sql
CREATE TABLE PATIENTS (
  patient_id STRING PRIMARY KEY,
  age INT,
  gender STRING,
  state STRING
);
```
Stores patient demographics and baseline information.

### CLAIMS Table
```sql
CREATE TABLE CLAIMS (
  claim_id STRING PRIMARY KEY,
  patient_id STRING,
  diagnosis_code STRING,        -- ICD-10 code
  procedure_code STRING,        -- HCPCS code
  date_of_service DATE
);
```
Stores medical claims, diagnoses, and procedures.

### POLICIES Table
```sql
CREATE TABLE POLICIES (
  policy_id STRING PRIMARY KEY,
  payer_name STRING,            -- Medicare, Aetna, etc.
  procedure_code STRING,        -- HCPCS code
  coverage_text STRING          -- Policy language
);
```
Stores insurance coverage policies and requirements.

**Relationships:**
- CLAIMS joins PATIENTS on `patient_id`
- CLAIMS joins POLICIES on `procedure_code` + `payer_name`
- Allows joining patient history with applicable coverage rules

---

## RAG (Retrieval-Augmented Generation) System

### Why RAG Instead of Pure LLM?
- ❌ **Pure LLM:** Hallucinates policy details ("I think coverage requires 6 weeks...")
- ✅ **RAG:** Retrieves actual policy language ("Policy states: coverage requires 6 weeks...")

### Chunking Strategy
Instead of arbitrary 500-character chunks, we chunk by **semantic sections**:
- Indications & Limitations
- Documentation Required
- Coverage Criteria
- Prior Auth Requirements

### Vector Database Choice
- **FAISS:** Simple, fast, free (open source)
- **all-MiniLM-L6-v2:** 384-dimensional embeddings (sufficient for medical text)
- **Workflow:** Extract → Chunk → Embed → Store → Query → Retrieve

---

## Deterministic Rules

Why not pure AI?
- Healthcare requires **explainability** - doctors need to see WHY a case was denied
- AI blackboxes are unacceptable in regulated industries
- Deterministic rules are **auditable and testable**

Example rule for Lumbar MRI:
```yaml
- rule: "conservative_treatment_weeks >= 6"
  severity: "critical"
  description: "Patient must have failed 6 weeks of conservative treatment"
```

Decision: **ALL rules must pass** for approval.

---

## Current Project Status

### ✅ COMPLETED
- [x] GitHub repository created and organized
- [x] README with complete project overview
- [x] Snowflake schema (3 tables designed)
- [x] dbt project configuration
- [x] dbt claims fact table model
- [x] Schema documentation
- [x] 2 sample policies downloaded (Medicare NCD + Aetna)
- [x] Chunking strategy configured
- [x] Vector DB design documented
- [x] Agent state defined (Python dataclass)
- [x] Deterministic rules configured
- [x] MCP server architecture designed

### 🚀 NEXT PHASE (After Demonstration)
- [ ] Implement Snowflake data loading
- [ ] Implement dbt transformations
- [ ] Implement FAISS vector DB with actual policies
- [ ] Implement RAG retrieval pipeline
- [ ] Implement agent workflow execution
- [ ] Add evaluation metrics (precision, recall, cycle time)
- [ ] Test with real/synthetic prior auth cases
- [ ] Integrate with actual payer APIs (future)

---

## Team

| Name | Role | Responsibility |
|------|------|-----------------|
| **Nancy** | Data Engineering Lead | Snowflake schema, dbt transformations, data pipeline |
| **Yashasvi** | RAG & Policy Lead | Policy retrieval, vector DB, semantic chunking |
| **Rekha** | Agent & Orchestration Lead | Workflow logic, deterministic rules, MCP servers |

---

## Key Metrics

- **Current Prior Auth Cycle Time:** 11-16 minutes
- **Target Cycle Time:** < 5 minutes (60% improvement)
- **Accuracy Target:** > 95% on clear cases
- **Audit Trail:** 100% - every decision logged with reasoning

---

## How to Demonstrate

### In Class, Show:
1. **GitHub Repo** - Organized structure with real files
2. **README.md** - Complete project overview (this file)
3. **SQL Schema** - 3 real tables with proper structure
4. **Policy Files** - Real Medicare & Aetna policies
5. **Chunking Config** - How policies are semantically chunked
6. **Agent State** - Python code defining agent workflow
7. **Rules Config** - Deterministic rules for decisions
8. **Complete Flow** - How patient data + policies → agent → decision

---

## Compliance & Standards

- ✅ **FHIR Compliant:** Uses HL7 FHIR standard for patient data
- ✅ **X12 Standards:** Uses industry-standard CARC/RARC denial codes
- ✅ **CMS Ready:** Aligns with CMS-0057-F (PA API requirements by Jan 2027)
- ✅ **Open Source:** Uses only open-source technologies (Snowflake, dbt, FAISS, LangGraph)
- ✅ **Auditable:** Deterministic rules are traceable and explainable

---

## References

- Medicare Coverage Database: https://www.cms.gov/medicare-coverage-database
- Synthea: https://github.com/synthetichealth/synthea
- X12 Standards: https://www.x12.org/
- HL7 FHIR: https://www.hl7.org/fhir/
- FAISS Documentation: https://github.com/facebookresearch/faiss
- LangGraph: https://github.com/langchain-ai/langgraph

---

## Contact & Questions

For questions about the project architecture, implementation details, or demonstration:
- Nancy (Data Engineering)
- Yashasvi (RAG & Policies)
- Rekha (Agent & Orchestration)

---


main
