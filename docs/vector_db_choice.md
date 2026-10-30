# Policy Retrieval (RAG) Design

Owner: Yashasvi · Code: `src/rag/rag_pipeline.py` · Config: `config/chunking_strategy.yaml`

## What this component does

Given a question such as "How many weeks of conservative treatment does Medicare require before a lumbar MRI?", it returns the policy sections that answer it, with payer, jurisdiction, section name and source file attached. The agent uses these sections as evidence for each rule it checks. It does not make the coverage decision itself.

## Current status

| Item | Status |
|------|--------|
| 8 synthetic policies, 7 procedures, 46 chunks | Working |
| Section-based chunking (with `skip_sections`) | Working |
| Embeddings (all-MiniLM-L6-v2) + FAISS index | Working |
| Cross-encoder reranking (default on) | Working |
| Hybrid search (keyword + embeddings) | Implemented, tested, not default |
| Filters: payer, procedure code, jurisdiction, state → jurisdiction | Working |
| Retrieval evaluation (22 own + 39 blind questions) | Working |
| Citation check against `criteria_rules.yaml` | Working |
| Policy metadata export for the Snowflake POLICIES table | Working |
| Policy documents | **Synthetic**, written by the team (real payer policies carry an AMA CPT license) |

## Policies

| Policy | Payer | Procedure codes | Jurisdiction |
|---|---|---|---|
| Lumbar spine MRI (LCD-style) | Medicare | 72148 | JK |
| Lumbar spine MRI | SampleCommercial | 72148 | national |
| Cervical spine MRI | SampleCommercial | 72141 | national |
| Knee MRI | SampleCommercial | 73721 | national |
| Brain MRI | SampleCommercial | 70551, 70553 | national |
| Lumbar epidural steroid injection | SampleCommercial | 62323, 64483 | national |
| Total knee arthroplasty | SampleCommercial | 27447 | national |
| Sleep apnea testing + CPAP | SampleCommercial | 95806, G0399, 95810, 95811, E0601 | national |

"SampleCommercial" is a fictional payer. Commercial policies share one layout (Precertification, Medical Necessity Criteria, Not Medically Necessary, Experimental/Investigational, Documentation Requirements, Background), modeled on how insurers structure clinical policy bulletins. No insurer text was copied. Procedure codes are listed by number with plain-language labels only.

## Pipeline

1. **Load** each policy file listed in the YAML config.
2. **Chunk** each file at its own section headings. Headings listed under `skip_sections` (Codes, Policy History) end a section but are not indexed. Text before the first heading (title, disclaimer) is skipped. Sections over 180 words are split into overlapping windows.
3. **Embed** each chunk with all-MiniLM-L6-v2 (384 dimensions), with payer and section name prefixed.
4. **Store** vectors in a FAISS `IndexFlatIP` (exact cosine similarity).
5. **Search**: rank all chunks, filter by payer, procedure code and jurisdiction, keep the top 10.
6. **Rerank**: a cross-encoder (ms-marco-MiniLM-L-6-v2) reads the question and each candidate together and reorders them. Scores are raw relevance scores, not percentages, and can be negative; only the order matters.

Each chunk has a stable ID, `policy_id::section_slug` (e.g. `medicare_lcd_lumbar_mri::red_flag_conditions`), which rules in `criteria_rules.yaml` cite.

## Why these choices

**Section-based chunking.** Policies are already organized into sections that each answer one kind of question, so splitting there keeps a criterion together with its conditions.

**FAISS.** Free, local, no server. Exact search is fine at tens of chunks.

**all-MiniLM-L6-v2.** Small, CPU-friendly, matches by meaning rather than shared words.

**Reranking.** Embeddings compare the question and each section separately. A cross-encoder reads them together, which should capture intent better. It was best on our own questions and was chosen as the default before the blind test; on blind questions it ties plain embeddings (see below).

**Region filter.** Medicare rules can differ by MAC jurisdiction. If no policy exists for a patient's region, the search returns nothing rather than another region's rules, and the agent should route the case to a human. `--state` converts a patient's state to its jurisdiction using `config/state_jurisdiction.yaml`.

## Evaluation results

### Own test set (22 questions)

8 "easy" (reuse policy wording), 14 "hard" (reworded the way a clinician would ask). A hit means the expected section is returned.

| Method | Section names | Easy @1 | Easy @3 | Hard @1 | Hard @3 | All @1 | All @3 |
|---|---|---|---|---|---|---|---|
| Keyword (TF-IDF) | yes | 7/8 | 8/8 | 7/14 | 12/14 | 14/22 | 20/22 |
| Keyword (TF-IDF) | no | 7/8 | 8/8 | 5/14 | 12/14 | 12/22 | 20/22 |
| Embeddings (FAISS) | yes | 5/8 | 8/8 | 10/14 | 13/14 | 15/22 | 21/22 |
| Embeddings (FAISS) | no | 4/8 | 8/8 | 8/14 | 13/14 | 12/22 | 21/22 |
| Hybrid (both) | yes | 7/8 | 7/8 | 9/14 | 13/14 | 16/22 | 20/22 |
| Hybrid (both) | no | 7/8 | 7/8 | 9/14 | 13/14 | 16/22 | 20/22 |
| **Embeddings + rerank** | yes | 7/8 | 8/8 | 11/14 | 13/14 | **18/22** | **21/22** |
| Hybrid + rerank | yes | 7/8 | 8/8 | 11/14 | 13/14 | 18/22 | 21/22 |

Findings:
- Keyword search wins when the question reuses policy wording; embeddings win on reworded questions.
- On this set, reranking is best. Compared with plain embeddings it fixed 4 questions and broke 1 ("What records must be sent with the prior authorization request?" now returns Precertification first).
- Embeddings + rerank and Hybrid + rerank score the same because, after the procedure filter, the top 10 candidates contain every section of the policy, so the reranker alone decides the order.
- On this set, section names helped embeddings (15/22 vs 12/22); this did not hold on blind questions.
- Still missed at #1 by the best method: one easy question and three hard ones, including "What paperwork does the surgeon need to send for a knee replacement?", which returns surgery criteria because the documentation section never mentions the knee. The model matches topic, not intent.

### Blind test (39 questions)

To check whether our own questions were too easy, we added 50 questions written without access to the policy files, from five perspectives (patient, doctor, insurance coordinator, caregiver, billing reviewer). The questions are kept exactly as written. 39 can be answered from our policies and are scored; 11 are not covered by any policy and are listed separately. Where two sections genuinely answer a question, either counts as correct. The answer key was written before running the evaluation. Questions and answer key: `config/blind_eval_questions.yaml`.

| Method | Section names | Blind @1 | Blind @3 |
|---|---|---|---|
| Keyword (TF-IDF) | yes | 16/39 | 30/39 |
| Keyword (TF-IDF) | no | 16/39 | 28/39 |
| Embeddings (FAISS) | yes | 23/39 | 34/39 |
| Embeddings (FAISS) | no | 24/39 | 33/39 |
| Hybrid (both) | yes | 21/39 | 34/39 |
| Hybrid (both) | no | 15/39 | 33/39 |
| Embeddings + rerank (default) | yes | 22/39 | 33/39 |
| Hybrid + rerank | yes | 22/39 | 33/39 |

Our own questions overestimated performance:

| Method | Own questions @1 (22) | Blind @1 (39) | Blind @3 (39) |
|---|---|---|---|
| Keyword | 14 (64%) | 16 (41%) | 30 (77%) |
| Embeddings | 15 (68%) | 23 (59%) | 34 (87%) |
| Hybrid | 16 (73%) | 21 (54%) | 34 (87%) |
| Embeddings + rerank | 18 (82%) | 22 (56%) | 33 (85%) |

Findings:
1. **Realistic performance is lower.** On questions written by someone else, the best methods return the correct section first about 56–59% of the time and in the top 3 about 85–87% of the time, compared with 82% at #1 on our own questions.
2. **The reranker's advantage did not carry over.** It was clearly best on our own questions, but on blind questions it ties plain embeddings (22 vs 23 at #1).
3. **We did not change the default based on this test.** Reranking was chosen before the blind test was run. Choosing a method by its blind score would make that score optimistic, so the blind set is kept as an honest held-out measure.
4. **Systematic weakness: documentation questions.** Many misses ask what to submit (e.g. "What documents should we submit to get a knee MRI approved?"). Retrieval matches the procedure topic rather than the documentation intent. For rule checks the agent already knows which section it needs, so it can request `…::documentation_requirements` directly by chunk ID; semantic search matters most for free-text questions.
5. **Coverage gap.** 11 of 50 questions (22%) ask about things no policy contains: appeals, referrals, approval timeframes, CPAP supplies, plan changes. A production system needs to say "not covered by this policy" instead of returning the closest section.
6. **Section names:** the earlier benefit does not hold on blind questions (embeddings 23 with vs 24 without), so we make no claim either way.

Caveats: the answer key was written by one person and should be reviewed by a second; 39 questions is still a small sample.

## Citation check

`python src/rag/rag_pipeline.py verify-citations` reads `config/criteria_rules.yaml`, checks that every `cites_chunk` exists, and flags codes or numbers in a rule that do not appear in the cited text. Results: `analysis/chunk_citation_verification.txt`. The first run found one rule with no citation (age ≥ 18) and one rule whose diagnosis code (M54.16) is not in the cited section.

## Known limitations

- **Small test sets.** 22 self-written questions plus 39 blind questions. Self-written questions overestimated accuracy (82% vs about 57% at #1 on blind questions). The blind answer key should be reviewed by a second person.
- **Documentation questions are a weak spot** (see blind test finding 4).
- **No "not covered" answer.** Questions outside the policies (about 22% of blind questions) still get the closest section.
- **Synthetic policies.** Realistic in structure but not any real insurer's text; uniform headings make chunking easier than real documents would.
- **FAISS has no metadata filtering.** Filters run after ranking; fine at this scale.
- **MiniLM is general-purpose,** not trained on medical text.
- **Only one Medicare region (JK) has a policy.** Medicare patients in other regions get no result by design.
- **State → jurisdiction map** should be verified against the current CMS MAC map.

## How to run

```bash
python -m pip install -r requirements.txt
python src/rag/rag_pipeline.py build                 # chunk + embed + save index
python src/rag/rag_pipeline.py demo                  # 3 example questions
python src/rag/rag_pipeline.py compare               # all methods side by side (own + blind questions)
python src/rag/rag_pipeline.py query "what documents are required" --payer Medicare --state MA
python src/rag/rag_pipeline.py verify-citations      # check criteria_rules.yaml citations
python src/rag/rag_pipeline.py export-metadata       # CSV for the POLICIES table
```

The first run downloads the embedding and reranker models (~180 MB). Without `faiss`/`sentence-transformers`, the script falls back to keyword search and prints a notice.

From Python (e.g. the agent):
```python
from rag_pipeline import get_retriever
r = get_retriever()   # same defaults as the CLI
results = r.search("documentation needed", payer="Medicare", procedure_code="72148", jurisdiction="JK", k=3)
```