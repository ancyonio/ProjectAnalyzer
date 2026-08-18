"""Pure-Python BM25 lexical index.

No third-party dependency, no network, no model download: the search command
works on an air-gapped build server on day one. Identifier-aware tokenisation
(`CreditScoreLookup` -> credit, score, lookup) is what makes it usable on
TIBCO artefact names, and query-time synonym expansion covers the
integration-domain vocabulary gap.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..constants import SEARCH_STOPWORDS, SEARCH_SYNONYMS
from ..utils import split_identifier

K1 = 1.5
B = 0.4              # mild length normalisation: process docs are legitimately long
NAME_BOOST = 3.0     # a hit in the artefact name counts triple
SNIPPET_BOOST = 1.5

# Prior on artefact kind. "Where is X implemented?" is answered by a process
# or a service far more often than by a single schema element, so the ranking
# reflects that before any query is seen.
LABEL_PRIORS = {
    'BWProcess': 1.8,
    'Service': 1.5,
    'Activity': 1.3,
    'DataTransformation': 1.2,
    'XSD': 1.1,
    'SharedResource': 1.1,
    'GlobalVariable': 1.0,
    'Operation': 1.0,
    'Module': 0.9,
    'ComplexType': 0.7,
    'Element': 0.6,
    'ErrorHandler': 0.8,
}


def tokenize(text: str, keep_stopwords: bool = False) -> List[str]:
    tokens = split_identifier(text)
    if keep_stopwords:
        return tokens
    return [t for t in tokens if t not in SEARCH_STOPWORDS and len(t) > 1]


def expand_query(tokens: Sequence[str]) -> List[Tuple[str, float]]:
    """Expand query tokens with domain synonyms at reduced weight."""
    out: Dict[str, float] = {}
    for t in tokens:
        out[t] = max(out.get(t, 0.0), 1.0)
        for syn in SEARCH_SYNONYMS.get(t, []):
            out[syn] = max(out.get(syn, 0.0), 0.45)
    return sorted(out.items(), key=lambda kv: -kv[1])


class BM25Index:
    """Okapi BM25 over the artefact corpus with field boosts."""

    def __init__(self) -> None:
        self.doc_ids: List[str] = []
        self.doc_len: List[int] = []
        self.term_freq: List[Dict[str, float]] = []
        self.doc_freq: Dict[str, int] = defaultdict(int)
        self.doc_boost: List[float] = []
        self.avg_len: float = 0.0
        self.n_docs: int = 0

    # ------------------------------------------------------------------
    def add_documents(self, docs: Iterable[Any]) -> None:
        for doc in docs:
            body = tokenize(doc.text)
            name = tokenize(doc.name)
            snippet = tokenize(doc.snippet)
            tf: Dict[str, float] = defaultdict(float)
            for t in body:
                tf[t] += 1.0
            for t in name:
                tf[t] += NAME_BOOST
            for t in snippet:
                tf[t] += SNIPPET_BOOST
            self.doc_ids.append(doc.doc_id)
            self.doc_boost.append(LABEL_PRIORS.get(doc.label, 1.0))
            self.term_freq.append(dict(tf))
            self.doc_len.append(max(1, len(body) + len(name) + len(snippet)))
            for term in tf:
                self.doc_freq[term] += 1
        self.n_docs = len(self.doc_ids)
        self.avg_len = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0

    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int = 20) -> List[Tuple[str, float, List[str]]]:
        """Return (doc_id, score, matched_terms) ranked by BM25."""
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        weighted = expand_query(q_tokens)
        scores: Dict[int, float] = defaultdict(float)
        matched: Dict[int, set] = defaultdict(set)

        for term, weight in weighted:
            df = self.doc_freq.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for idx, tf_map in enumerate(self.term_freq):
                tf = tf_map.get(term)
                if not tf:
                    continue
                denom = tf + K1 * (1 - B + B * self.doc_len[idx] / (self.avg_len or 1))
                scores[idx] += weight * idf * (tf * (K1 + 1)) / denom
                if weight >= 1.0:
                    matched[idx].add(term)

        for idx in list(scores):
            scores[idx] *= self.doc_boost[idx] if idx < len(self.doc_boost) else 1.0

        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]
        return [(self.doc_ids[i], round(score, 4), sorted(matched[i])) for i, score in ranked]

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            'docIds': self.doc_ids,
            'docLen': self.doc_len,
            'docBoost': self.doc_boost,
            'termFreq': self.term_freq,
            'docFreq': dict(self.doc_freq),
            'avgLen': self.avg_len,
            'nDocs': self.n_docs,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'BM25Index':
        idx = BM25Index()
        idx.doc_ids = d['docIds']
        idx.doc_len = d['docLen']
        idx.doc_boost = d.get('docBoost', [1.0] * len(d['docIds']))
        idx.term_freq = d['termFreq']
        idx.doc_freq = defaultdict(int, d['docFreq'])
        idx.avg_len = d['avgLen']
        idx.n_docs = d['nDocs']
        return idx
