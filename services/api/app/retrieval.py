"""Deterministic, explainable evidence retrieval over the knowledge base.

This is what actually grounds an agent's findings in ``workflow.py``: a real
(if intentionally dependency-free) TF-IDF weighted cosine-similarity search
over every ``KnowledgeDocument`` in the database, run against a query built
from the case under analysis. It replaces the previous approach of picking
evidence by hand for one hardcoded ``case_id`` — every score below is
computed from the actual text of the case and the documents, so the same
case always retrieves the same evidence for the same reason, and a reviewer
can see *why* a document was cited (its similarity score) instead of being
asked to trust a label.

Both English and Simplified Chinese text are indexed side by side (every
``KnowledgeDocument`` field is a bilingual ``{"en": ..., "zh": ...}`` value),
so a query built from either language can still retrieve evidence authored
in the other — no translation call is required for retrieval to work.

No external search/ML dependency is introduced: this is plain Python, which
keeps the engine auditable and runnable fully offline, matching the rest of
the platform's "deterministic demo mode" posture when no external model is
configured (see ``llm.py``).
"""
import math
import re
from collections import Counter

_LATIN_WORD_RE = re.compile(r"[a-z0-9]+(?:[./\-][a-z0-9]+)*")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """Split text into search tokens.

    Latin-script words (including dotted/hyphenated identifiers such as
    ``c-14.2`` or ``schedule.analyze``) are kept whole and lowercased; CJK
    text has no whitespace to split on and no segmenter dependency is
    available, so each Chinese character becomes its own token. That is a
    weak signal for any single character but an adequate one in aggregate
    for short, keyword-dense engineering/contract text like this corpus.
    """
    if not text:
        return []
    lowered = text.lower()
    tokens = _LATIN_WORD_RE.findall(lowered)
    tokens.extend(_CJK_RE.findall(lowered))
    return tokens


_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def tokenize_bigrams(text: str) -> list[str]:
    """Like ``tokenize`` but splits CJK runs into overlapping character pairs.

    Single characters are too ambiguous for a large corpus of short clause
    summaries (天 in 露天 "open air" would match 天气 "weather"); pairs keep
    most of the recall while removing those accidental matches. A one-
    character run is kept as-is.
    """
    if not text:
        return []
    lowered = text.lower()
    tokens = _LATIN_WORD_RE.findall(lowered)
    # A hyphenated word also counts as its parts, so "end-of-service" in a
    # clause matches a query that writes "end of service".
    tokens.extend(part for token in tokens if "-" in token for part in token.split("-") if part)
    # A plain English plural also counts as its singular ("crossings" ->
    # "crossing", "committees" -> "committee"); no stemmer dependency.
    tokens.extend(token[:-1] for token in list(tokens) if len(token) > 4 and token.endswith("s")
                  and not token.endswith(("ss", "us", "is")) and token.isalpha())
    for run in _CJK_RUN_RE.findall(lowered):
        tokens.extend([run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)])
    return tokens


def _bilingual_text(value) -> str:
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if v)
    if isinstance(value, list):
        return " ".join(_bilingual_text(v) for v in value)
    return str(value) if value else ""


def document_text(doc) -> str:
    """Flatten the searchable bilingual fields of a KnowledgeDocument."""
    fields = (doc.title, doc.category, doc.jurisdiction, doc.content, doc.summary, doc.source_ref)
    return " ".join(_bilingual_text(f) for f in fields if f)


def case_query_text(case) -> str:
    """Flatten the bilingual fields of a Case into one retrieval query."""
    parts = [case.type, case.title, case.description, *case.detected_issues]
    return " ".join(_bilingual_text(p) for p in parts if p)


# Clause-level statutory summaries (``knowledge_data/*.jsonl``) are scored in
# their own tier. Without this, ~100 short clause paraphrases would dominate
# document frequency and silently shift every operational source's cosine
# score below the calibrated confidence thresholds used by the agents.
CLAUSE_TIER_DOCUMENT_TYPES = frozenset({"CLAUSE_SUMMARY"})


def document_tier(doc) -> str:
    return "clause" if getattr(doc, "document_type", None) in CLAUSE_TIER_DOCUMENT_TYPES else "source"


class _TfIdfTier:
    """A tiny in-memory TF-IDF index over a fixed set of documents."""

    def __init__(self, docs: list, tokenizer=tokenize):
        self.docs = list(docs)
        self.tokenizer = tokenizer
        doc_tokens = [Counter(tokenizer(document_text(d))) for d in self.docs]
        document_frequency: Counter = Counter()
        for counts in doc_tokens:
            for term in counts:
                document_frequency[term] += 1
        n_docs = max(len(self.docs), 1)
        # Smoothed IDF: terms present in every document contribute ~1x
        # weight, rare terms contribute more, and the +1 floor keeps
        # previously-unseen query terms from ever hitting a hard zero.
        self.idf = {term: math.log((n_docs + 1) / (df + 1)) + 1.0 for term, df in document_frequency.items()}
        self.doc_vectors = [self._vectorize(counts) for counts in doc_tokens]

    def _vectorize(self, term_counts: Counter) -> dict:
        vector = {term: count * self.idf.get(term, 1.0) for term, count in term_counts.items()}
        norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
        return {term: v / norm for term, v in vector.items()}

    def score(self, query: str) -> list[tuple[float, object]]:
        query_counts = Counter(self.tokenizer(query))
        if not query_counts:
            return []
        query_vector = self._vectorize(query_counts)
        scored = []
        for doc, doc_vector in zip(self.docs, self.doc_vectors):
            score = sum(weight * doc_vector.get(term, 0.0) for term, weight in query_vector.items())
            if score > 1e-9:
                scored.append((score, doc))
        return scored


TIER_TOKENIZERS = {"source": tokenize, "clause": tokenize_bigrams}


class KnowledgeIndex:
    """TF-IDF cosine search over documents, scored per corpus tier.

    Operational source documents and clause-level statutory summaries each
    get their own IDF statistics (and the clause tier uses CJK character
    pairs); results from both tiers are merged by cosine similarity. A corpus with no clause documents behaves exactly as
    a single TF-IDF index over all documents.
    """

    def __init__(self, docs: list):
        self.docs = list(docs)
        grouped: dict[str, list] = {}
        for doc in self.docs:
            grouped.setdefault(document_tier(doc), []).append(doc)
        self.tiers = {name: _TfIdfTier(members, TIER_TOKENIZERS[name]) for name, members in grouped.items()}

    def search(self, query: str, top_k: int = 3) -> list[tuple[float, object]]:
        """Return up to ``top_k`` ``(cosine_similarity, document)`` pairs,
        highest similarity first, for documents with any term overlap."""
        scored = [pair for tier in self.tiers.values() for pair in tier.score(query)]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:top_k]
