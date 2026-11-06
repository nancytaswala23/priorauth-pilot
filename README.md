# PriorAuthPilot

**Checks a prior authorization request against the payer's policy before it is submitted.**

PriorAuthPilot combines patient and claim data, retrieval of the applicable insurance policy, and deterministic rules to produce an auditable assessment of a prior authorization (PA) request: whether it meets the policy's criteria, which policy text each check is based on, and what should happen next.

> **All data and policies in this project are synthetic.** The system *assesses* requests and recommends a next step; only the insurer approves or denies. Not for clinical or billing use.

**Team:** Nancy Taswala (data engineering) · Yashasvi Nagar (policy retrieval / RAG) · Avadhanam Vinaya Rekha (agent and rules)
**Course:** DAMG 6300, Northeastern University

---

## Contents

1. [The problem](#the-problem)
2. [What the system does](#what-the-system-does)
3. [Architecture](#architecture)
4. [Setup guide](#setup-guide)
5. [How to run the project](#how-to-run-the-project)
6. [Using the app](#using-the-app)
7. [Command reference](#command-reference)
8. [Results](#results)
9. [Project structure](#project-structure)
10. [Data and policies](#data-and-policies)
11. [Limitations and next steps](#limitations-and-next-steps)
12. [Troubleshooting](#troubleshooting)
13. [References](#references)

---

## The problem

Before certain treatments, a provider must get the insurer's permission: prior authorization. It is high-volume and slow. As cited in Awan & Raza (2026), from the 2023 AMA Prior Authorization Physician Survey:

- U.S. physicians submit **100 million+** PA requests a year
- Physicians spend about **14 hours a week** on PA documentation
- **94%** report care delays tied to prior authorization

Coverage criteria are fragmented: Medicare rules vary by region (Local Coverage Determinations, by Medicare Administrative Contractor), and every commercial insurer publishes its own policies in its own format.

Our project builds on the research paper *AI-Generated Prior Authorization Letters: Strong Clinical Content, Weak Administrative Scaffolding* (Awan & Raza, 2026). The paper found that LLMs write clinically strong PA letters but miss administrative elements and payer-specific criteria, and it recommends a hybrid system: retrieve payer criteria, fill administrative details deterministically, and route unclear cases to a human. PriorAuthPilot implements that scaffolding.

---

## What the system does

For one claim, the system:

1. **Reads the claim and patient** (procedure, diagnosis, treatment history, red flags, insurer, state)
2. **Finds the policy that applies**, filtered by payer, procedure code and the patient's Medicare region (MAC jurisdiction)
3. **Checks deterministic rules**, each citing the exact policy section it comes from
4. **Produces an assessment** and a recommended next step:

| Assessment | Meaning |
|---|---|
| `MEETS_CRITERIA` | The request meets the policy's criteria |
| `NEEDS_DOCS` | Documentation is missing |
| `DOES_NOT_MEET_CRITERIA` | At least one policy rule is not met |

| Routing | Next step |
|---|---|
| `READY_TO_SUBMIT` | Submit to the insurer; the insurer decides |
| `REQUEST_DOCUMENTATION` | Ask the provider for the missing information |
| `HUMAN_REVIEW` | A staff member reviews before anything is submitted |

5. **Adds administrative elements** the paper found missing: billing code, authorization duration and follow-up plan (the last two are labeled *team assumption* because no policy states them)
6. **Generates a PDF report** of the assessment

If no policy exists for the payer or region, the system returns nothing rather than another region's rules, and routes the case to a human.

---

## Architecture

```
 Patient & claim data        Policy retrieval              Rules agent                 Output
 (Nancy)                     (Yashasvi)                    (Rekha)
┌──────────────────┐   ┌──────────────────────────┐   ┌──────────────────────┐   ┌───────────────────┐
│ Snowflake         │   │ 8 synthetic policies     │   │ Deterministic rules  │   │ Assessment        │
│ → local DuckDB    │──▶│ 46 sections (chunks)     │──▶│ (criteria_rules.yaml)│──▶│ + routing         │
│ PATIENTS, CLAIMS, │   │ MiniLM embeddings + FAISS│   │ each rule cites a    │   │ + admin elements  │
│ POLICIES          │   │ + cross-encoder reranker │   │ policy chunk_id      │   │ + PDF report      │
└──────────────────┘   │ filter: payer, procedure,│   └──────────────────────┘   └───────────────────┘
                        │ Medicare region          │
                        └──────────────────────────┘
                                   │ no policy for payer/region → human review
```

**Built and working:** data layer (DuckDB copy of the warehouse), policy retrieval, deterministic rules, Streamlit app, PDF report, evaluation and integration checks.
**Designed, not yet built:** LangGraph orchestration, the three MCP servers (see `docs/mcp_design.md`), real payer submission and status tracking.

### Technology

| Layer | Technology |
|---|---|
| Data warehouse | Snowflake (schema + dbt models); local DuckDB copy for the demo |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions) |
| Vector index | FAISS (`IndexFlatIP`, exact cosine similarity) |
| Reranking | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Rules | Python + YAML (`config/criteria_rules.yaml`) |
| App | Streamlit |
| PDF report | ReportLab |

---

## Setup guide

### Prerequisites

- **Python 3.10–3.13**
- **Git**
- About **1 GB** of free disk space
- **Internet on the first run**: the search models (~180 MB) are downloaded once and cached

### 1. Clone the repository

```bash
git clone https://github.com/nancytaswala23/priorauth-pilot.git
cd priorauth-pilot
```

### 2. (Recommended) Create a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Build the local database

Builds `priorauth.duckdb` from the CSV files. Safe to re-run.

```bash
python setup_duckdb.py
python add_procedures.py
```

### 5. Build the policy search index

Splits the policies into sections, creates embeddings and saves the FAISS index. The first run downloads the models.

```bash
python src/rag/rag_pipeline.py build
```

Expected output starts with: `Built index: 46 chunks from 8 policies (backend: faiss, 384-dim vectors, ...)`

### 6. (Optional) Run the pre-flight check

Stop the app first; it locks the database file.

```bash
python preflight_check.py
```

> On macOS/Linux, use `python3` instead of `python` if needed. On Windows, `py` also works.

---

## How to run the project

```bash
python -m streamlit run app.py
```

The app opens at **http://localhost:8501**.

To stop it, press **Ctrl+C** in the terminal.

---

## Using the app

1. **Select a claim in the sidebar.** The app opens on claim **C10001**. The toggle *Only procedures in our policy library* hides claims such as office visits.
2. **Data tab:** patient and claim details, and the patient's claim history.
3. **Policy tab:** the matching policy (payer, procedure, policy region, patient region) and its sections. Type a question to run the live search (FAISS + reranker), which returns the top 3 sections with scores.
4. **Assessment tab:** click **Run assessment**. Shows the result, the key facts behind it, and each rule as PASS/FAIL with the policy text it is based on.
5. **Summary tab:** the next step, administrative elements, the policy used, and **Download report (PDF)**.

### Example cases

| Claim | Expected |
|---|---|
| **C10001** (P1000, lumbar MRI with contrast, SampleCommercial, CA, 3 weeks of treatment, no red flag) | `DOES_NOT_MEET_CRITERIA` → human review |
| A claim with `red_flag_present = true` and under 6 weeks | Passes the 6-week rule through the red-flag exception |
| A Medicare patient outside region JK (e.g. CA) | No policy for that region → human review |
| An office visit (99213 / 99214) | Not in our policy library |

---

## Command reference

### Policy retrieval (`src/rag/rag_pipeline.py`)

```bash
python src/rag/rag_pipeline.py build                    # build the index
python src/rag/rag_pipeline.py demo                     # 3 example questions
python src/rag/rag_pipeline.py query "what documents are required" --payer Medicare --state MA
python src/rag/rag_pipeline.py compare                  # compare all retrieval methods
python src/rag/rag_pipeline.py eval                     # accuracy on the test questions
python src/rag/rag_pipeline.py verify-citations         # check rules cite real policy text
python src/rag/rag_pipeline.py check-data               # check claims data against the policy library
python src/rag/rag_pipeline.py export-metadata          # CSV for the POLICIES table
```

Useful options: `--payer`, `--procedure`, `--jurisdiction`, `--state`, `--backend auto|faiss|tfidf|hybrid`, `--no-rerank`.

### Policy lookup for one claim (`src/rag/retrieve_policy.py`)

```bash
python src/rag/retrieve_policy.py 72149 SampleCommercial CA
python src/rag/retrieve_policy.py 72148 Medicare MA "how many weeks of therapy are needed?"
```

### Integration test

```bash
python test_integration.py
```

---

## Results

All numbers come from runs in this repository (`analysis/`).

### Policy retrieval

| Method | Own questions, correct at #1 (22) | Blind questions, correct at #1 (39) | Blind, correct in top 3 (39) |
|---|---|---|---|
| Keyword search (TF-IDF) | 14 (64%) | 16 (41%) | 30 (77%) |
| Embeddings (FAISS) | 15 (68%) | 23 (59%) | 34 (87%) |
| **Embeddings + reranker (default)** | **18 (82%)** | 22 (56%) | 33 (85%) |

Blind questions were written without access to the policy files; the answer key was set before running the test. Our own questions overestimated accuracy, and the reranker's advantage did not carry over to blind questions. The reranker remains the default because it was chosen before the blind test. See `docs/vector_db_choice.md`.

### System checks

| Check | Result |
|---|---|
| Lumbar MRI claims that find their policy (`check-data`) | 199 / 199 |
| Rule fields present in the data | All present |
| Rule citations that point to real policy sections (`verify-citations`) | All resolve; age rule labeled team assumption |
| Integration test (`test_integration.py`) | Passing |

---

## Project structure

```
priorauth-pilot/
├── app.py                         # Streamlit app
├── app_panels/
│   ├── ui.py                      # shared UI components (cards, tiles, stepper)
│   ├── policy_panel.py            # Policy tab display
│   └── report_pdf.py              # PDF assessment report
├── assets/                        # logo
├── .streamlit/config.toml         # app theme
├── setup_duckdb.py                # builds priorauth.duckdb from CSVs
├── add_procedures.py              # adds the procedures table
├── preflight_check.py             # pre-demo checks
├── test_integration.py            # cross-team integration test
├── requirements.txt
│
├── config/
│   ├── chunking_strategy.yaml     # policy files, sections, payers, regions, procedure codes
│   ├── criteria_rules.yaml        # deterministic rules with policy citations
│   ├── state_jurisdiction.yaml    # state → Medicare region (MAC jurisdiction)
│   └── blind_eval_questions.yaml  # blind test questions + answer key
│
├── data/
│   ├── patients_sample.csv        # synthetic patients (100)
│   ├── claims_sample.csv          # synthetic claims (313)
│   ├── processed/policies_metadata.csv
│   └── raw/policies/              # 8 synthetic policies
│
├── src/
│   ├── rag/
│   │   ├── rag_pipeline.py        # chunking, embeddings, FAISS, reranker, evaluation, checks
│   │   └── retrieve_policy.py     # policy lookup used by the agent and the app
│   ├── agent/
│   │   ├── agent_state.py
│   │   └── evaluate_claim.py      # rule evaluation and assessment
│   ├── ui/data_panel.py           # DuckDB access helpers
│   ├── data_pipeline/             # Snowflake schema
│   └── mcp_servers/               # MCP server design (planned)
│
├── scripts/                       # synthetic data generators
├── dbt/                           # dbt project and models
├── analysis/                      # test and check results
└── docs/
    ├── vector_db_choice.md        # retrieval design and evaluation
    ├── snowflake_schema.md
    └── mcp_design.md
```

---

## Data and policies

### Data

Patients and claims are **synthetic**, generated by the scripts in `scripts/` (randomly assigned values; not derived from real records). The data lives in Snowflake; `setup_duckdb.py` loads a local DuckDB copy for the app.

| Table | Rows | Key columns |
|---|---|---|
| PATIENTS | 100 | patient_id, age, gender, state, insurance |
| CLAIMS | 313 | claim_id, patient_id, procedure_code, diagnosis_code, date_of_service, conservative_treatment_weeks, red_flag_present |
| POLICIES | 14 | policy_id, payer_name, procedure_code, document_type, jurisdiction, synthetic (8 policies; one row per policy and procedure code) |

### Policies

Eight **synthetic** policies, written in our own words. Real payer pages were used only as a structural reference, because real payer policies are copyrighted and contain AMA-licensed CPT content.

| Policy | Payer | Procedure codes | Region |
|---|---|---|---|
| Lumbar spine MRI (LCD-style) | Medicare | 72148, 72149, 72158 | JK |
| Lumbar spine MRI | SampleCommercial | 72148, 72149, 72158 | national |
| Cervical spine MRI | SampleCommercial | 72141 | national |
| Knee MRI | SampleCommercial | 73721 | national |
| Brain MRI | SampleCommercial | 70551, 70553 | national |
| Lumbar epidural steroid injection | SampleCommercial | 62323, 64483 | national |
| Total knee arthroplasty | SampleCommercial | 27447 | national |
| Sleep apnea testing + CPAP | SampleCommercial | 95806, G0399, 95810, 95811, E0601 | national |

*SampleCommercial* is a fictional payer.

### Rules (lumbar MRI)

| Rule | Basis |
|---|---|
| At least 6 weeks of conservative treatment, **or** a red flag | Policy |
| Qualifying radiculopathy diagnosis (M54.16, M54.17, M51.16), **or** a red flag | Policy, with a hand-checked code mapping |
| Patient is 18 or older | Team assumption (not stated in any policy) |

---

## Limitations and next steps

**Limitations**
- Synthetic data and policies; results do not reflect real payer behavior
- Small test sets (22 own + 39 blind questions); the blind answer key was set by one person
- Only one Medicare region (JK) has a policy; rules cover lumbar MRI only
- Approval outcomes and latency are not measured
- Authorization duration and follow-up plan are team assumptions

**Next steps**
- Generate the PA letter with an LLM from our structured, cited output (the paper's full hybrid approach)
- Return an explicit "not covered by policy" answer for questions outside the policies
- Second reviewer for the blind answer key; more blind questions
- LangGraph orchestration and the MCP servers
- Real data and submission path via HL7 FHIR (Da Vinci PAS) and X12 278

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `streamlit` is not recognized | Run `python -m streamlit run app.py` |
| "Running in TF-IDF FALLBACK mode" | `faiss-cpu` or `sentence-transformers` is missing: `python -m pip install -r requirements.txt` |
| First run is slow | The search models (~180 MB) are downloading; later runs use the cache |
| Database is locked | Stop the running app (Ctrl+C) before running `setup_duckdb.py` or `preflight_check.py` |
| Error about `st.toggle`, `st.logo` or `border` | Upgrade Streamlit: `python -m pip install --upgrade streamlit` |
| The app still shows the old layout | Stop all running Streamlit processes, restart, and refresh with Ctrl+F5 |
| PDF download fails | `python -m pip install reportlab` |

---

## References

- Awan, M. S., & Raza, M. (2026). *AI-Generated Prior Authorization Letters: Strong Clinical Content, Weak Administrative Scaffolding.* arXiv:2603.29366
- [Medicare Coverage Database](https://www.cms.gov/medicare-coverage-database)
- [HL7 Da Vinci Prior Authorization Support](https://hl7.org/fhir/us/davinci-pas/)
- [FAISS](https://github.com/facebookresearch/faiss)
- [Sentence-Transformers](https://www.sbert.net/)
- [Streamlit](https://streamlit.io/)