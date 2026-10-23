"""
PriorAuthPilot - Policy RAG pipeline (owner: Yashasvi)

What it does:
  1. Reads config/chunking_strategy.yaml
  2. Loads each policy file and splits it at its section headings
  3. Embeds each chunk with all-MiniLM-L6-v2 (384-dim vectors)
  4. Stores the vectors in a FAISS index (data/index/)
  5. Answers questions by returning the most relevant policy chunks,
     filtered by payer, procedure code and jurisdiction

Usage (run from the repo root):
  pip install -r requirements.txt
  python src/rag/rag_pipeline.py build
  python src/rag/rag_pipeline.py query "How long must conservative treatment last?" --payer Medicare --jurisdiction JK
  python src/rag/rag_pipeline.py demo
  python src/rag/rag_pipeline.py eval
  python src/rag/rag_pipeline.py compare

Options for every command:
  --backend auto|faiss|tfidf|hybrid
                               faiss = embeddings (default when installed), tfidf = keyword search,
                               hybrid = both, merged with reciprocal rank fusion
  --no-section-names           embed chunks WITHOUT the section heading prefix (experiment)
  --rerank                     re-score the top 10 candidates with a cross-encoder model

Note: the first run downloads the embedding model (~90 MB), so run it once
with internet before presenting.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "chunking_strategy.yaml"
INDEX_DIR = REPO_ROOT / "data" / "index"
INDEX_FILE = INDEX_DIR / "policies.faiss"
CHUNKS_FILE = INDEX_DIR / "chunks.json"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_CANDIDATES = 10


# ---------------------------------------------------------------- chunking

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _norm(line):
    """Lowercase, trim, drop a trailing colon, collapse spaces."""
    return re.sub(r"\s+", " ", line.strip().rstrip(":")).lower()


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def split_into_sections(text, headings, skip_headings=()):
    """Split text at lines that exactly match one of the configured headings.
    Text before the first heading (title, disclaimer) is not indexed.
    A skip heading ends the current section, and its own text is not indexed."""
    heading_lookup = {_norm(h): h for h in headings}
    skip_lookup = {_norm(h) for h in skip_headings}
    sections, current, buffer = [], None, []
    for line in text.splitlines():
        key = _norm(line)
        if key in heading_lookup or key in skip_lookup:
            if current is not None:
                sections.append((current, " ".join(buffer).strip()))
            current = heading_lookup.get(key)  # None for skip headings
            buffer = []
        elif current is not None and line.strip():
            buffer.append(line.strip())
    if current is not None:
        sections.append((current, " ".join(buffer).strip()))

    found = {name for name, _ in sections}
    missing = [h for h in headings if h not in found]
    return sections, missing


def window(words, max_words, overlap):
    """Break an over-long section into overlapping word windows."""
    if len(words) <= max_words:
        return [" ".join(words)]
    step = max_words - overlap
    return [" ".join(words[i:i + max_words])
            for i in range(0, len(words) - overlap, step)]


def build_chunks(config, warn=True):
    defaults = config.get("defaults", {})
    max_words = defaults.get("max_words", 180)
    overlap = defaults.get("overlap_words", 30)
    chunks = []

    for policy in config["policies"]:
        path = REPO_ROOT / policy["file"]
        if not path.exists():
            sys.exit(f"ERROR: policy file not found: {path}")
        text = path.read_text(encoding="utf-8")
        sections, missing = split_into_sections(text, policy["sections"],
                                                policy.get("skip_sections", []))
        codes = policy.get("procedure_codes") or [policy["procedure_code"]]
        if missing and warn:
            print(f"WARNING [{policy['policy_id']}]: headings not found in file: {missing}")

        for section_name, body in sections:
            if not body:
                continue
            parts = window(body.split(), max_words, overlap)
            for i, part in enumerate(parts):
                suffix = f"__part{i + 1}" if len(parts) > 1 else ""
                chunks.append({
                    # stable id, so rules in criteria_rules.yaml can cite it
                    "chunk_id": f"{policy['policy_id']}::{_slug(section_name)}{suffix}",
                    "policy_id": policy["policy_id"],
                    "payer": policy["payer"],
                    "jurisdiction": str(policy.get("jurisdiction", "national")),
                    "document_type": policy.get("document_type", ""),
                    "procedure_codes": [str(code) for code in codes],
                    "section": section_name,
                    "synthetic": bool(policy.get("synthetic", False)),
                    "source_file": policy["file"],
                    "text": part,
                })
    return chunks


def embed_text(chunk, use_section_names=True):
    """Text that actually gets embedded. The section-name prefix is optional
    so we can measure whether it helps or hurts retrieval."""
    if use_section_names:
        return f"{chunk['payer']} | {chunk['section']}: {chunk['text']}"
    return f"{chunk['payer']}: {chunk['text']}"


def matches_filters(chunk, payer=None, procedure_code=None, jurisdiction=None):
    if payer and payer.lower() not in chunk["payer"].lower():
        return False
    if procedure_code and str(procedure_code) not in chunk["procedure_codes"]:
        return False
    if jurisdiction:
        j = chunk.get("jurisdiction", "national").lower()
        if j not in (jurisdiction.lower(), "national"):
            return False
    return True


# --------------------------------------------------------------- backends

def faiss_available():
    try:
        import faiss  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401
        return True
    except ImportError:
        return False


def resolve_backend(requested="auto", quiet=False):
    if requested in ("faiss", "hybrid") or (requested == "auto" and faiss_available()):
        if not faiss_available():
            sys.exit("ERROR: faiss / sentence-transformers not installed. "
                     "Run: python -m pip install -r requirements.txt")
        if requested == "hybrid":
            try:
                import sklearn  # noqa: F401
            except ImportError:
                sys.exit("ERROR: hybrid mode also needs scikit-learn: python -m pip install scikit-learn")
            return "hybrid"
        return "faiss"
    try:
        import sklearn  # noqa: F401
    except ImportError:
        sys.exit("ERROR: install requirements first:  python -m pip install -r requirements.txt")
    if requested == "auto" and not quiet:
        print("NOTE: faiss / sentence-transformers not installed. "
              "Running in TF-IDF FALLBACK mode (not the real embedding pipeline).")
    return "tfidf"


RRF_K = 60  # standard reciprocal rank fusion constant


_model = None


def encode(texts):
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    vecs = _model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype="float32")


_reranker = None


def rerank(query, candidates, use_section_names=True):
    """Cross-encoder reranking: the model reads the question and each candidate
    together, which captures intent better than comparing separate vectors."""
    global _reranker
    if not candidates:
        return candidates
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(RERANK_MODEL)
    pairs = [(query, embed_text(c, use_section_names)) for c in candidates]
    scores = _reranker.predict(pairs, show_progress_bar=False)
    rescored = [{**c, "score": round(float(s), 4)} for c, s in zip(candidates, scores)]
    return sorted(rescored, key=lambda c: -c["score"])


class Retriever:
    """Holds the chunks plus either a FAISS index (embeddings) or a TF-IDF matrix (keywords)."""

    def __init__(self, chunks, backend, use_section_names=True):
        self.chunks = chunks
        self.backend = backend
        self.use_section_names = use_section_names
        self.rerank = False
        texts = [embed_text(c, use_section_names) for c in chunks]
        if backend in ("faiss", "hybrid"):
            import faiss
            vectors = encode(texts)
            self.index = faiss.IndexFlatIP(vectors.shape[1])  # inner product on unit vectors = cosine
            self.index.add(vectors)
        if backend in ("tfidf", "hybrid"):
            from sklearn.feature_extraction.text import TfidfVectorizer
            self.vectorizer = TfidfVectorizer(stop_words="english")
            self.matrix = self.vectorizer.fit_transform(texts)

    @classmethod
    def load_saved(cls, chunks, use_section_names):
        """Reuse the FAISS index saved by `build`, but only if it matches the
        current policies and settings; otherwise return None."""
        if not (INDEX_FILE.exists() and CHUNKS_FILE.exists()):
            return None
        with open(CHUNKS_FILE, encoding="utf-8") as f:
            meta = json.load(f)
        if (meta.get("backend") != "faiss" or meta.get("chunks") != chunks
                or meta.get("use_section_names", True) != use_section_names):
            return None
        import faiss
        r = cls.__new__(cls)
        r.chunks, r.backend, r.use_section_names = chunks, "faiss", use_section_names
        r.rerank = False
        r.index = faiss.read_index(str(INDEX_FILE))
        return r

    def _rank_embeddings(self, query):
        scores, ids = self.index.search(encode([query]), len(self.chunks))
        return [(float(s), int(i)) for s, i in zip(scores[0], ids[0]) if i >= 0]

    def _rank_keywords(self, query):
        from sklearn.metrics.pairwise import cosine_similarity
        sims = cosine_similarity(self.vectorizer.transform([query]), self.matrix)[0]
        return sorted(((float(s), i) for i, s in enumerate(sims)), key=lambda x: -x[0])

    def search(self, query, payer=None, procedure_code=None, jurisdiction=None, k=3):
        if self.backend == "faiss":
            ranked = self._rank_embeddings(query)
        elif self.backend == "tfidf":
            ranked = self._rank_keywords(query)
        else:
            # Hybrid: reciprocal rank fusion. Each method votes 1 / (60 + rank);
            # chunks ranked high by either method rise to the top.
            fused = {}
            for ranking in (self._rank_embeddings(query), self._rank_keywords(query)):
                for rank, (_, i) in enumerate(ranking, 1):
                    fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank)
            ranked = sorted(((score, i) for i, score in fused.items()), key=lambda x: -x[0])

        # FAISS has no built-in metadata filtering, so filter here after ranking.
        limit = max(k, RERANK_CANDIDATES) if self.rerank else k
        results = []
        for score, i in ranked:
            c = self.chunks[i]
            if not matches_filters(c, payer, procedure_code, jurisdiction):
                continue
            results.append({**c, "score": round(score, 4)})
            if len(results) == limit:
                break
        if self.rerank:
            results = rerank(query, results, self.use_section_names)[:k]
        return results


def get_retriever(backend="auto", use_section_names=True, quiet=False, use_rerank=False):
    chunks = build_chunks(load_config(), warn=not quiet)
    backend = resolve_backend(backend, quiet=quiet)
    if use_rerank and not faiss_available():
        sys.exit("ERROR: --rerank needs sentence-transformers: python -m pip install -r requirements.txt")
    r = None
    if backend == "faiss":
        r = Retriever.load_saved(chunks, use_section_names)
    if r is None:
        r = Retriever(chunks, backend, use_section_names)
    r.rerank = use_rerank
    return r


def describe(r):
    return f"(backend: {r.backend}, section names: {r.use_section_names}, rerank: {r.rerank})"


# ------------------------------------------------------------------- build

def cmd_build(args):
    chunks = build_chunks(load_config())
    if not chunks:
        sys.exit("ERROR: no chunks produced. Check section headings in the YAML.")
    backend = resolve_backend(args.backend)
    use_names = not args.no_section_names
    r = Retriever(chunks, backend, use_names)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    dim = None
    if backend in ("faiss", "hybrid"):
        import faiss
        faiss.write_index(r.index, str(INDEX_FILE))
        dim = r.index.d
    with open(CHUNKS_FILE, "w", encoding="utf-8") as f:
        # "faiss" here means the saved file holds the embedding index
        json.dump({"backend": "faiss" if dim else backend, "model": MODEL_NAME, "dim": dim,
                   "use_section_names": use_names, "chunks": chunks}, f, indent=2)

    print(f"Built index: {len(chunks)} chunks from "
          f"{len({c['policy_id'] for c in chunks})} policies (backend: {backend}"
          f"{', ' + str(dim) + '-dim vectors' if dim else ''}, section names: {use_names})")
    for c in chunks:
        flag = " [SYNTHETIC]" if c["synthetic"] else ""
        print(f"  - {c['chunk_id']}  ({len(c['text'].split())} words, "
              f"jurisdiction={c['jurisdiction']}){flag}")


# ------------------------------------------------------------------ search

def print_results(query, results):
    print(f"\nQUERY: {query}")
    if not results:
        print("  (no matching chunks for those filters)")
    for rank, r in enumerate(results, 1):
        flag = "  [SYNTHETIC SAMPLE]" if r["synthetic"] else ""
        print(f"\n  #{rank}  score={r['score']}  {r['chunk_id']}{flag}")
        print(f"      payer={r['payer']} | jurisdiction={r['jurisdiction']} | "
              f"section={r['section']} | file={r['source_file']}")
        print(f"      {r['text']}")


def cmd_query(args):
    r = get_retriever(args.backend, not args.no_section_names, use_rerank=args.rerank)
    print(describe(r))
    print_results(args.question, r.search(args.question, args.payer, args.procedure,
                                          args.jurisdiction, args.k))


DEMO_QUERIES = [
    ("How many weeks of conservative treatment are needed before a lumbar MRI?", "Medicare"),
    ("Which symptoms allow an MRI without waiting six weeks?", None),
    ("What records must be sent with the prior authorization request?", "SampleCommercial"),
]


def cmd_demo(args):
    r = get_retriever(args.backend, not args.no_section_names, use_rerank=args.rerank)
    print(describe(r))
    for q, payer in DEMO_QUERIES:
        print_results(f"{q}  (payer filter: {payer or 'none'})",
                      r.search(q, payer, "72148", k=2))


# -------------------------------------------------------------------- eval
M = "medicare_lcd_lumbar_mri::"
C = "commercial_lumbar_mri::"

# (difficulty, question, payer filter, procedure code, chunk that should come back)
# "easy" questions reuse words from the policy text.
# "hard" questions are reworded the way a clinician or staff member would ask.
EVAL_SET = [
    ("easy", "minimum duration of physical therapy or medication before imaging", "Medicare", "72148",
     M + "coverage_indications_limitations_and_or_medical_necessity"),
    ("easy", "bladder dysfunction or saddle numbness", "Medicare", "72148", M + "red_flag_conditions"),
    ("easy", "repeat MRI within a year", "Medicare", "72148", M + "limitations"),
    ("easy", "what should the medical record include", "Medicare", "72148", M + "documentation_requirements"),
    ("easy", "request submitted after the service was performed", "SampleCommercial", "72148",
     C + "precertification_requirements"),
    ("easy", "when is the scan not medically necessary", "SampleCommercial", "72148",
     C + "not_medically_necessary"),
    ("easy", "clinical notes from the last 60 days", "SampleCommercial", "72148",
     C + "documentation_requirements"),
    ("easy", "pre-operative planning for scheduled surgery", "SampleCommercial", "72148",
     C + "medical_necessity_criteria"),

    ("hard", "How many weeks of conservative treatment are needed before a lumbar MRI?", "Medicare", "72148",
     M + "coverage_indications_limitations_and_or_medical_necessity"),
    ("hard", "Which symptoms allow an MRI without waiting six weeks?", "Medicare", "72148",
     M + "red_flag_conditions"),
    ("hard", "What records must be sent with the prior authorization request?", "SampleCommercial", "72148",
     C + "documentation_requirements"),
    ("hard", "Patient suddenly can't control their bladder, can we scan today?", "Medicare", "72148",
     M + "red_flag_conditions"),
    ("hard", "Will Medicare pay for a back scan if the pain started two weeks ago and nothing looks alarming?",
     "Medicare", "72148", M + "limitations"),
    ("hard", "Can we still get approval if the scan was already done?", "SampleCommercial", "72148",
     C + "precertification_requirements"),
    ("hard", "What does the chart need to say about the therapy the patient already tried?", "Medicare", "72148",
     M + "documentation_requirements"),
    ("hard", "Does the plan cover a scan for someone with no symptoms, just to check?", "SampleCommercial", "72148",
     C + "not_medically_necessary"),

    # one reworded question for each of the other commercial policies
    ("hard", "She drops things and walks unsteadily, does she have to finish six weeks of therapy before a neck scan?",
     "SampleCommercial", "72141", "commercial_cervical_mri::medical_necessity_criteria"),
    ("hard", "The X-ray already shows bone-on-bone arthritis, will the plan also pay for a knee MRI?",
     "SampleCommercial", "73721", "commercial_knee_mri::not_medically_necessary"),
    ("hard", "He has had the same migraines for ten years and his neuro exam is normal, can he get a head scan?",
     "SampleCommercial", "70553", "commercial_brain_mri::not_medically_necessary"),
    ("hard", "The first back injection only helped for three weeks, can we book another one?",
     "SampleCommercial", "62323", "commercial_lumbar_esi::medical_necessity_criteria"),
    ("hard", "What paperwork does the surgeon need to send for a knee replacement?",
     "SampleCommercial", "27447", "commercial_total_knee_arthroplasty::documentation_requirements"),
    ("hard", "She only wore her breathing machine a couple of hours a night this month, will the plan keep paying?",
     "SampleCommercial", "E0601", "commercial_sleep_apnea::medical_necessity_criteria"),
]


def run_eval(retriever, k=3):
    rows = []
    for difficulty, q, payer, code, expected in EVAL_SET:
        ids = [r["chunk_id"] for r in retriever.search(q, payer, code, k=k)]
        rows.append({"difficulty": difficulty, "question": q, "expected": expected,
                     "top": ids[0] if ids else None,
                     "hit1": ids[:1] == [expected], "hitk": expected in ids})
    return rows


def summarize(rows, difficulty):
    sub = [r for r in rows if r["difficulty"] == difficulty]
    return sum(r["hit1"] for r in sub), sum(r["hitk"] for r in sub), len(sub)


def cmd_eval(args):
    r = get_retriever(args.backend, not args.no_section_names, use_rerank=args.rerank)
    print(describe(r) + "\n")
    rows = run_eval(r, args.k)
    for row in rows:
        status = "PASS" if row["hit1"] else (f"top-{args.k}" if row["hitk"] else "MISS")
        print(f"  {status:6} [{row['difficulty']}] {row['question']}")
        if not row["hit1"]:
            print(f"         expected {row['expected']}, got {row['top']}")
    for d in ("easy", "hard"):
        h1, hk, n = summarize(rows, d)
        print(f"\n{d.upper():5} Hit@1: {h1}/{n}   Hit@{args.k}: {hk}/{n}", end="")
    h1, hk, n = sum(x["hit1"] for x in rows), sum(x["hitk"] for x in rows), len(rows)
    print(f"\nALL   Hit@1: {h1}/{n} ({h1 / n:.0%})   Hit@{args.k}: {hk}/{n} ({hk / n:.0%})")


def cmd_compare(args):
    # (backend, section names, rerank)
    configs = [("tfidf", True, False), ("tfidf", False, False)]
    if faiss_available():
        configs += [("faiss", True, False), ("faiss", False, False),
                    ("hybrid", True, False), ("hybrid", False, False),
                    ("faiss", True, True), ("hybrid", True, True)]
    else:
        print("NOTE: faiss / sentence-transformers not installed, so only keyword search is compared.\n")

    k = args.k
    results = []
    for backend, names, use_rerank in configs:
        rows = run_eval(get_retriever(backend, names, quiet=True, use_rerank=use_rerank), k)
        results.append((backend, names, use_rerank, rows))

    base = {"tfidf": "Keyword (TF-IDF)", "faiss": "Embeddings (FAISS)", "hybrid": "Hybrid (both)"}

    def label(backend, use_rerank):
        return base[backend] + (" + rerank" if use_rerank else "")

    print(f"{'Method':28} {'Section names':14} {'Easy @1':>8} {'Easy @' + str(k):>8} "
          f"{'Hard @1':>8} {'Hard @' + str(k):>8} {'All @1':>8} {'All @' + str(k):>8}")
    print("-" * 98)
    for backend, names, use_rerank, rows in results:
        e1, ek, en = summarize(rows, "easy")
        h1, hk, hn = summarize(rows, "hard")
        print(f"{label(backend, use_rerank):28} {('yes' if names else 'no'):14} "
              f"{f'{e1}/{en}':>8} {f'{ek}/{en}':>8} {f'{h1}/{hn}':>8} {f'{hk}/{hn}':>8} "
              f"{f'{e1 + h1}/{en + hn}':>8} {f'{ek + hk}/{en + hn}':>8}")

    print("\nQuestions missed at #1:")
    for backend, names, use_rerank, rows in results:
        misses = [r for r in rows if not r["hit1"]]
        print(f"\n  {label(backend, use_rerank)}, section names {'yes' if names else 'no'}: "
              f"{len(misses)} missed")
        for r in misses:
            print(f"    - [{r['difficulty']}] {r['question']}")


# -------------------------------------------------------------------- main

def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--backend", choices=["auto", "faiss", "tfidf", "hybrid"], default="auto",
                        help="faiss = embeddings, tfidf = keyword search, hybrid = both (default: auto)")
    common.add_argument("--no-section-names", action="store_true",
                        help="embed chunks without the section heading prefix")
    common.add_argument("--rerank", action=argparse.BooleanOptionalAction, default=True,
                        help="re-score the top 10 candidates with a cross-encoder")

    parser = argparse.ArgumentParser(description="PriorAuthPilot policy RAG pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build", parents=[common], help="chunk policies, embed, and save the index")

    q = sub.add_parser("query", parents=[common], help="search the policy index")
    q.add_argument("question")
    q.add_argument("--payer", help="filter by payer, e.g. Medicare")
    q.add_argument("--procedure", help="filter by procedure code, e.g. 72148")
    q.add_argument("--jurisdiction", help="filter by jurisdiction, e.g. JK (national policies always match)")
    q.add_argument("-k", type=int, default=3, help="number of results")

    sub.add_parser("demo", parents=[common], help="run the class demo queries")

    e = sub.add_parser("eval", parents=[common], help="measure retrieval accuracy on the test set")
    e.add_argument("-k", type=int, default=3)

    c = sub.add_parser("compare", help="compare keyword vs embeddings, with and without section names")
    c.add_argument("-k", type=int, default=3)

    args = parser.parse_args()
    {"build": cmd_build, "query": cmd_query, "demo": cmd_demo,
     "eval": cmd_eval, "compare": cmd_compare}[args.command](args)


if __name__ == "__main__":
    main()