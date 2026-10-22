"""
PriorAuthPilot - Policy RAG pipeline (owner: Yashasvi)

What it does:
  1. Reads config/chunking_strategy.yaml
  2. Loads each policy file and splits it at its section headings
  3. Embeds each chunk with all-MiniLM-L6-v2 (384-dim vectors)
  4. Stores the vectors in a FAISS index (data/index/)
  5. Answers questions by returning the most relevant policy chunks,
     filtered by payer and procedure code

Usage (run from the repo root):
  pip install -r requirements.txt
  python src/rag/rag_pipeline.py build
  python src/rag/rag_pipeline.py query "How long must conservative treatment last?" --payer Medicare
  python src/rag/rag_pipeline.py demo
  python src/rag/rag_pipeline.py eval

Note: the first build downloads the embedding model (~90 MB), so run it once
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


def build_chunks(config):
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
        if missing:
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
                    "document_type": policy.get("document_type", ""),
                    "procedure_code": str(policy["procedure_code"]),
                    "section": section_name,
                    "synthetic": bool(policy.get("synthetic", False)),
                    "source_file": policy["file"],
                    "text": part,
                })
    return chunks


def embed_text(chunk):
    """Prefix payer + section so the vector carries that context too."""
    return f"{chunk['payer']} | {chunk['section']}: {chunk['text']}"


# --------------------------------------------------------------- embedding

def detect_backend():
    """Use FAISS + MiniLM if installed; otherwise a clearly labelled TF-IDF fallback."""
    try:
        import faiss  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401
        return "faiss"
    except ImportError:
        try:
            import sklearn  # noqa: F401
            print("NOTE: faiss / sentence-transformers not installed. "
                  "Running in TF-IDF FALLBACK mode (not the real embedding pipeline).")
            return "tfidf"
        except ImportError:
            sys.exit("ERROR: install requirements first:  pip install -r requirements.txt")


_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode(texts):
    vecs = get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype="float32")


# ------------------------------------------------------------------- build

def cmd_build(_args=None):
    chunks = build_chunks(load_config())
    if not chunks:
        sys.exit("ERROR: no chunks produced. Check section headings in the YAML.")
    backend = detect_backend()
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    if backend == "faiss":
        import faiss
        vectors = encode([embed_text(c) for c in chunks])
        index = faiss.IndexFlatIP(vectors.shape[1])  # inner product on unit vectors = cosine
        index.add(vectors)
        faiss.write_index(index, str(INDEX_FILE))
        dim = vectors.shape[1]
    else:
        dim = None

    with open(CHUNKS_FILE, "w", encoding="utf-8") as f:
        json.dump({"backend": backend, "model": MODEL_NAME, "dim": dim,
                   "chunks": chunks}, f, indent=2)

    print(f"Built index: {len(chunks)} chunks from "
          f"{len({c['policy_id'] for c in chunks})} policies (backend: {backend}"
          f"{', ' + str(dim) + '-dim vectors' if dim else ''})")
    for c in chunks:
        flag = " [SYNTHETIC]" if c["synthetic"] else ""
        print(f"  - {c['chunk_id']}  ({len(c['text'].split())} words){flag}")


# ------------------------------------------------------------------ search

def load_index():
    if not CHUNKS_FILE.exists():
        cmd_build()
    with open(CHUNKS_FILE, encoding="utf-8") as f:
        return json.load(f)


def search(query, payer=None, procedure_code=None, k=3):
    store = load_index()
    chunks = store["chunks"]

    if store["backend"] == "faiss":
        import faiss
        index = faiss.read_index(str(INDEX_FILE))
        scores, ids = index.search(encode([query]), len(chunks))
        ranked = [(float(s), int(i)) for s, i in zip(scores[0], ids[0]) if i >= 0]
    else:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(stop_words="english")
        matrix = vec.fit_transform([embed_text(c) for c in chunks])
        sims = cosine_similarity(vec.transform([query]), matrix)[0]
        ranked = sorted(((float(s), i) for i, s in enumerate(sims)), reverse=True)

    # FAISS has no built-in metadata filtering, so filter here after ranking.
    results = []
    for score, i in ranked:
        c = chunks[i]
        if payer and payer.lower() not in c["payer"].lower():
            continue
        if procedure_code and str(procedure_code) != c["procedure_code"]:
            continue
        results.append({**c, "score": round(score, 3)})
        if len(results) == k:
            break
    return results


def print_results(query, results):
    print(f"\nQUERY: {query}")
    if not results:
        print("  (no matching chunks for that payer / procedure)")
    for rank, r in enumerate(results, 1):
        flag = "  [SYNTHETIC SAMPLE]" if r["synthetic"] else ""
        print(f"\n  #{rank}  score={r['score']}  {r['chunk_id']}{flag}")
        print(f"      payer={r['payer']} | section={r['section']} | file={r['source_file']}")
        print(f"      {r['text']}")


def cmd_query(args):
    print_results(args.question,
                  search(args.question, args.payer, args.procedure, args.k))


DEMO_QUERIES = [
    ("How many weeks of conservative treatment are needed before a lumbar MRI?", "Medicare"),
    ("Which symptoms allow an MRI without waiting six weeks?", None),
    ("What records must be sent with the prior authorization request?", "SampleCommercial"),
]


def cmd_demo(_args):
    for q, payer in DEMO_QUERIES:
        print_results(f"{q}  (payer filter: {payer or 'none'})", search(q, payer, "72148", k=2))


# -------------------------------------------------------------------- eval
# Small hand-labelled test set: question -> chunk that should be retrieved.
EVAL_SET = [
    ("minimum duration of physical therapy or medication before imaging", "Medicare",
     "medicare_lcd_lumbar_mri::coverage_indications_limitations_and_or_medical_necessity"),
    ("bladder dysfunction or saddle numbness", "Medicare",
     "medicare_lcd_lumbar_mri::red_flag_conditions"),
    ("repeat MRI within a year", "Medicare",
     "medicare_lcd_lumbar_mri::limitations"),
    ("what should the medical record include", "Medicare",
     "medicare_lcd_lumbar_mri::documentation_requirements"),
    ("request submitted after the service was performed", "SampleCommercial",
     "commercial_lumbar_mri::prior_authorization_requirements"),
    ("when is the scan not medically necessary", "SampleCommercial",
     "commercial_lumbar_mri::exclusions"),
    ("clinical notes from the last 60 days", "SampleCommercial",
     "commercial_lumbar_mri::documentation_requirements"),
    ("pre-operative planning for scheduled surgery", "SampleCommercial",
     "commercial_lumbar_mri::coverage_criteria"),
]


def cmd_eval(args):
    k = args.k
    hits1 = hitsk = 0
    for q, payer, expected in EVAL_SET:
        ids = [r["chunk_id"] for r in search(q, payer, "72148", k=k)]
        h1, hk = ids[:1] == [expected], expected in ids
        hits1 += h1
        hitsk += hk
        print(f"  {'PASS' if h1 else ('top-' + str(k)) if hk else 'MISS'}  {q}")
    n = len(EVAL_SET)
    print(f"\nHit@1: {hits1}/{n} ({hits1 / n:.0%})   Hit@{k}: {hitsk}/{n} ({hitsk / n:.0%})")


# -------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="PriorAuthPilot policy RAG pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build", help="chunk policies, embed, and save the index")

    q = sub.add_parser("query", help="search the policy index")
    q.add_argument("question")
    q.add_argument("--payer", help="filter by payer, e.g. Medicare")
    q.add_argument("--procedure", help="filter by CPT code, e.g. 72148")
    q.add_argument("-k", type=int, default=3, help="number of results")

    sub.add_parser("demo", help="run the class demo queries")

    e = sub.add_parser("eval", help="measure retrieval accuracy on a labelled test set")
    e.add_argument("-k", type=int, default=3)

    args = parser.parse_args()
    {"build": cmd_build, "query": cmd_query,
     "demo": cmd_demo, "eval": cmd_eval}[args.command](args)


if __name__ == "__main__":
    main()