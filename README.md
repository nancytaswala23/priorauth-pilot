# PriorAuthPilot: Agentic AI for Healthcare Prior Authorization

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
