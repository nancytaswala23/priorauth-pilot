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
  --backend auto|faiss|tfidf   faiss = embeddings (default when installed), tfidf = keyword search
  --no-section-names           embed chunks WITHOUT the section heading prefix (experiment)

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


# ---------------------------------------------------------------- chunking

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _norm(line):
    """Lowercase, trim, drop a trailing colon, collapse spaces."""
    return re.sub(r"\s+", " ", line.strip().rstrip(":")).lower()


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def split_into_sections(text, headings):
    """Split text at lines that exactly match one of the configured headings.
    Text before the first heading (title, disclaimer) is not indexed."""
    heading_lookup = {_norm(h): h for h in headings}
    sections, current, buffer = [], None, []
    for line in text.splitlines():
        key = _norm(line)
        if key in heading_lookup:
            if current is not None:
                sections.append((current, " ".join(buffer).strip()))
            current, buffer = heading_lookup[key], []
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
        sections, missing = split_into_sections(text, policy["sections"])
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
                    "procedure_code": str(policy["procedure_code"]),
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
    if procedure_code and str(procedure_code) != chunk["procedure_code"]:
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
    if requested == "faiss" or (requested == "auto" and faiss_available()):
        if not faiss_available():
            sys.exit("ERROR: faiss / sentence-transformers not installed. "
                     "Run: python -m pip install -r requirements.txt")
        return "faiss"
    try:
        import sklearn  # noqa: F401
    except ImportError:
        sys.exit("ERROR: install requirements first:  python -m pip install -r requirements.txt")
    if requested == "auto" and not quiet:
        print("NOTE: faiss / sentence-transformers not installed. "
              "Running in TF-IDF FALLBACK mode (not the real embedding pipeline).")
    return "tfidf"


_model = None


def encode(texts):
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    vecs = _model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype="float32")


class Retriever:
    """Holds the chunks plus either a FAISS index (embeddings) or a TF-IDF matrix (keywords)."""

    def __init__(self, chunks, backend, use_section_names=True):
        self.chunks = chunks
        self.backend = backend
        self.use_section_names = use_section_names
        texts = [embed_text(c, use_section_names) for c in chunks]
        if backend == "faiss":
            import faiss
            vectors = encode(texts)
            self.index = faiss.IndexFlatIP(vectors.shape[1])  # inner product on unit vectors = cosine
            self.index.add(vectors)
        else:
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
        r.index = faiss.read_index(str(INDEX_FILE))
        return r

    def search(self, query, payer=None, procedure_code=None, jurisdiction=None, k=3):
        if self.backend == "faiss":
            scores, ids = self.index.search(encode([query]), len(self.chunks))
            ranked = [(float(s), int(i)) for s, i in zip(scores[0], ids[0]) if i >= 0]
        else:
            from sklearn.metrics.pairwise import cosine_similarity
            sims = cosine_similarity(self.vectorizer.transform([query]), self.matrix)[0]
            ranked = sorted(((float(s), i) for i, s in enumerate(sims)), key=lambda x: -x[0])

        # FAISS has no built-in metadata filtering, so filter here after ranking.
        results = []
        for score, i in ranked:
            c = self.chunks[i]
            if not matches_filters(c, payer, procedure_code, jurisdiction):
                continue
            results.append({**c, "score": round(score, 3)})
            if len(results) == k:
                break
        return results


def get_retriever(backend="auto", use_section_names=True, quiet=False):
    chunks = build_chunks(load_config(), warn=not quiet)
    backend = resolve_backend(backend, quiet=quiet)
    if backend == "faiss":
        saved = Retriever.load_saved(chunks, use_section_names)
        if saved:
            return saved
    return Retriever(chunks, backend, use_section_names)


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
    if backend == "faiss":
        import faiss
        faiss.write_index(r.index, str(INDEX_FILE))
        dim = r.index.d
    with open(CHUNKS_FILE, "w", encoding="utf-8") as f:
        json.dump({"backend": backend, "model": MODEL_NAME, "dim": dim,
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
    r = get_retriever(args.backend, not args.no_section_names)
    print_results(args.question, r.search(args.question, args.payer, args.procedure,
                                          args.jurisdiction, args.k))


DEMO_QUERIES = [
    ("How many weeks of conservative treatment are needed before a lumbar MRI?", "Medicare"),
    ("Which symptoms allow an MRI without waiting six weeks?", None),
    ("What records must be sent with the prior authorization request?", "SampleCommercial"),
]


def cmd_demo(args):
    r = get_retriever(args.backend, not args.no_section_names)
    print(f"(backend: {r.backend}, section names: {r.use_section_names})")
    for q, payer in DEMO_QUERIES:
        print_results(f"{q}  (payer filter: {payer or 'none'})",
                      r.search(q, payer, "72148", k=2))


# -------------------------------------------------------------------- eval
M = "medicare_lcd_lumbar_mri::"
C = "commercial_lumbar_mri::"

# (difficulty, question, payer filter, chunk that should come back)
# "easy" questions reuse words from the policy text.
# "hard" questions are reworded the way a clinician or staff member would ask.
EVAL_SET = [
    ("easy", "minimum duration of physical therapy or medication before imaging", "Medicare",
     M + "coverage_indications_limitations_and_or_medical_necessity"),
    ("easy", "bladder dysfunction or saddle numbness", "Medicare", M + "red_flag_conditions"),
    ("easy", "repeat MRI within a year", "Medicare", M + "limitations"),
    ("easy", "what should the medical record include", "Medicare", M + "documentation_requirements"),
    ("easy", "request submitted after the service was performed", "SampleCommercial",
     C + "prior_authorization_requirements"),
    ("easy", "when is the scan not medically necessary", "SampleCommercial", C + "exclusions"),
    ("easy", "clinical notes from the last 60 days", "SampleCommercial", C + "documentation_requirements"),
    ("easy", "pre-operative planning for scheduled surgery", "SampleCommercial", C + "coverage_criteria"),

    ("hard", "How many weeks of conservative treatment are needed before a lumbar MRI?", "Medicare",
     M + "coverage_indications_limitations_and_or_medical_necessity"),
    ("hard", "Which symptoms allow an MRI without waiting six weeks?", "Medicare",
     M + "red_flag_conditions"),
    ("hard", "What records must be sent with the prior authorization request?", "SampleCommercial",
     C + "documentation_requirements"),
    ("hard", "Patient suddenly can't control their bladder, can we scan today?", "Medicare",
     M + "red_flag_conditions"),
    ("hard", "Will Medicare pay for a back scan if the pain started two weeks ago and nothing looks alarming?",
     "Medicare", M + "limitations"),
    ("hard", "Can we still get approval if the scan was already done?", "SampleCommercial",
     C + "prior_authorization_requirements"),
    ("hard", "What does the chart need to say about the therapy the patient already tried?", "Medicare",
     M + "documentation_requirements"),
    ("hard", "Does the plan cover a scan for someone with no symptoms, just to check?", "SampleCommercial",
     C + "exclusions"),
]


def run_eval(retriever, k=3):
    rows = []
    for difficulty, q, payer, expected in EVAL_SET:
        ids = [r["chunk_id"] for r in retriever.search(q, payer, "72148", k=k)]
        rows.append({"difficulty": difficulty, "question": q, "expected": expected,
                     "top": ids[0] if ids else None,
                     "hit1": ids[:1] == [expected], "hitk": expected in ids})
    return rows


def summarize(rows, difficulty):
    sub = [r for r in rows if r["difficulty"] == difficulty]
    return sum(r["hit1"] for r in sub), sum(r["hitk"] for r in sub), len(sub)


def cmd_eval(args):
    r = get_retriever(args.backend, not args.no_section_names)
    print(f"(backend: {r.backend}, section names: {r.use_section_names})\n")
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
    configs = [("tfidf", True), ("tfidf", False)]
    if faiss_available():
        configs += [("faiss", True), ("faiss", False)]
    else:
        print("NOTE: faiss / sentence-transformers not installed, so only keyword search is compared.\n")

    k = args.k
    results = []
    for backend, names in configs:
        rows = run_eval(get_retriever(backend, names, quiet=True), k)
        results.append((backend, names, rows))

    label = {"tfidf": "Keyword (TF-IDF)", "faiss": "Embeddings (FAISS)"}
    print(f"{'Method':20} {'Section names':14} {'Easy @1':>8} {'Easy @' + str(k):>8} "
          f"{'Hard @1':>8} {'Hard @' + str(k):>8}")
    print("-" * 70)
    for backend, names, rows in results:
        e1, ek, en = summarize(rows, "easy")
        h1, hk, hn = summarize(rows, "hard")
        print(f"{label[backend]:20} {('yes' if names else 'no'):14} {f'{e1}/{en}':>8} {f'{ek}/{en}':>8} "
              f"{f'{h1}/{hn}':>8} {f'{hk}/{hn}':>8}")

    print("\nHard questions missed at #1:")
    for backend, names, rows in results:
        misses = [r["question"] for r in rows if r["difficulty"] == "hard" and not r["hit1"]]
        print(f"\n  {label[backend]}, section names {'yes' if names else 'no'}: "
              f"{len(misses)} missed")
        for q in misses:
            print(f"    - {q}")


# -------------------------------------------------------------------- main

def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--backend", choices=["auto", "faiss", "tfidf"], default="auto",
                        help="faiss = embeddings, tfidf = keyword search (default: auto)")
    common.add_argument("--no-section-names", action="store_true",
                        help="embed chunks without the section heading prefix")

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