# Policy Retrieval (RAG) Design

Owner: Yashasvi · Code: `src/rag/rag_pipeline.py` · Config: `config/chunking_strategy.yaml`

## What this component does

Given a question such as "How many weeks of conservative treatment does Medicare require before a lumbar MRI?", it returns the policy passages that answer it, with the payer, section, and source file attached. The agent uses these passages as evidence for each rule it checks. It does not make the coverage decision itself.

## Current status

| Item | Status |
|------|--------|
| Chunking by section headings | Working |
| Embedding with all-MiniLM-L6-v2 + FAISS index | Implemented |
| Payer / proced`` ure filtering | Working |
| Retrieval evaluation (Hit@1, Hit@3) | Working, small test set |
| Policy documents | **Synthetic samples**, to be replaced with a real Medicare LCD and a real commercial payer policy |

## Pipeline

1. **Load** each policy file listed in the YAML config.
2. **Chunk** each file at its own section headings (for example "Coverage Criteria" or "Documentation Requirements"). Text before the first heading, such as the title and disclaimer, is skipped. A section longer than 180 words is split into overlapping 180-word windows.
3. **Embed** each chunk with all-MiniLM-L6-v2. The payer and section name are prefixed to the text so the vector carries that context.
4. **Store** the vectors in a FAISS `IndexFlatIP` (exact search; with normalized vectors, inner product equals cosine similarity).
5. **Search**: embed the question, rank all chunks, then filter by payer and CPT code, and return the top k.

Each chunk has a stable ID such as `medicare_lcd_lumbar_mri::documentation_requirements`, so a rule in `criteria_rules.yaml` can cite the exact passage it came from.

## Why these choices

**Section-based chunking.** Coverage policies are already organized into sections that each answer one kind of question. Splitting there keeps a criterion and its conditions together, which fixed-length chunks can cut in half. Matching on exact headings is simpler and more predictable than keyword matching. Keyword matching is fragile because, for example, "covered" also matches "not covered."

**FAISS.** It's free, runs locally, and needs no server. Exact search (`IndexFlatIP`) is fine at our size, which is tens of chunks. Approximate indexes only matter at hundreds of thousands of vectors.

**all-MiniLM-L6-v2.** It's small (about 90 MB), produces 384-dimensional vectors, and runs on a laptop CPU. It matches by meaning, not just shared words, so "bladder dysfunction" can find a section about cauda equina symptoms.

## Known limitations

- **FAISS has no metadata filtering.** Payer and procedure filters are applied in our code after ranking. That's fine at this scale but wasteful at large scale. A vector database with built-in filtering, such as pgvector or Qdrant, would replace it.
- **MiniLM is a general-purpose model, not trained on medical text.** It may miss clinical synonyms. A biomedical embedding model is the obvious upgrade to test.
- **The model reads only about 256 tokens per chunk.** That's why sections are capped at 180 words.
- **Heading matching depends on each document's format.** Real policies need their headings listed in the YAML, and the script warns when a configured heading isn't found.
- **The evaluation set is small and was written by the same person who wrote the policies,** so the scores are optimistic. A fair test needs questions written by someone else, against real documents.

## How to run

```bash
pip install -r requirements.txt
python src/rag/rag_pipeline.py build      # chunk + embed + save index
python src/rag/rag_pipeline.py demo       # 3 example questions
python src/rag/rag_pipeline.py eval       # Hit@1 / Hit@3 on the test set
python src/rag/rag_pipeline.py query "what documents are required" --payer Medicare
```

If `faiss` or `sentence-transformers` isn't installed, the script falls back to TF-IDF keyword search and prints a notice. This keeps it runnable anywhere, but it is not the intended pipeline.
   ## Evaluation results

   16 questions: 8 "easy" (reuse policy wording), 8 "hard" (reworded like a clinician would ask).

   | Method | Section names | Easy @1 | Easy @3 | Hard @1 | Hard @3 |
   |---|---|---|---|---|---|
   | Keyword (TF-IDF) | yes / no | 7/8 | 8/8 | 2/8 | 6/8 |
   | Embeddings (FAISS) | yes / no | 7/8 | 8/8 | 5/8 | 8/8 |

   - Easy questions can't tell the methods apart; reworded questions can.
   - Adding section names to chunks had no measurable effect.
   - All remaining embedding misses still appear in the top 3, so the agent should read the top 3 results.
   - Caveat: small test set, written by the pipeline's author. Next step is questions written blind by teammates.