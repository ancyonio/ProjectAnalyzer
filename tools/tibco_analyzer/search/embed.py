"""Optional vector layer for semantic search.

Strictly optional and strictly degradable: if no provider is available the
engine runs lexical-only and says so. Providers are tried in order:

1. `sentence-transformers` (local, offline, no key)     -- pip install sentence-transformers
2. OpenAI-compatible embeddings endpoint                -- OPENAI_API_KEY (+ optional OPENAI_BASE_URL)
3. Azure OpenAI embeddings                              -- AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT

Vectors are cached next to the index and keyed by a hash of the document
text, so re-indexing after a partial change only re-embeds what changed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger('tibco_analyzer')


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:32]


class EmbeddingProvider:
    name = 'none'
    dim = 0

    def available(self) -> bool:
        return False

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError


class SentenceTransformerProvider(EmbeddingProvider):
    name = 'sentence-transformers'

    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        self.model_name = model_name
        self._model = None

    def available(self) -> bool:
        try:
            import sentence_transformers  # noqa: F401
            return True
        except Exception:
            return False

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        model = self._load()
        return [list(map(float, v)) for v in model.encode(list(texts), show_progress_bar=False)]


class OpenAIProvider(EmbeddingProvider):
    name = 'openai'

    def __init__(self, model: str = 'text-embedding-3-small'):
        self.model = os.environ.get('OPENAI_EMBEDDING_MODEL', model)

    def available(self) -> bool:
        if not os.environ.get('OPENAI_API_KEY'):
            return False
        try:
            import openai  # noqa: F401
            return True
        except Exception:
            return False

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        from openai import OpenAI
        client = OpenAI(base_url=os.environ.get('OPENAI_BASE_URL') or None)
        out: List[List[float]] = []
        for i in range(0, len(texts), 64):
            batch = [t[:8000] for t in texts[i:i + 64]]
            resp = client.embeddings.create(model=self.model, input=batch)
            out.extend([d.embedding for d in resp.data])
        return out


class AzureOpenAIProvider(EmbeddingProvider):
    name = 'azure-openai'

    def available(self) -> bool:
        if not (os.environ.get('AZURE_OPENAI_API_KEY') and os.environ.get('AZURE_OPENAI_ENDPOINT')):
            return False
        try:
            import openai  # noqa: F401
            return True
        except Exception:
            return False

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=os.environ['AZURE_OPENAI_API_KEY'],
            azure_endpoint=os.environ['AZURE_OPENAI_ENDPOINT'],
            api_version=os.environ.get('AZURE_OPENAI_API_VERSION', '2024-02-01'),
        )
        deployment = os.environ.get('AZURE_OPENAI_EMBEDDING_DEPLOYMENT', 'text-embedding-3-small')
        out: List[List[float]] = []
        for i in range(0, len(texts), 32):
            batch = [t[:8000] for t in texts[i:i + 32]]
            resp = client.embeddings.create(model=deployment, input=batch)
            out.extend([d.embedding for d in resp.data])
        return out


PROVIDERS = [SentenceTransformerProvider, OpenAIProvider, AzureOpenAIProvider]


def resolve_provider(preferred: Optional[str] = None) -> Optional[EmbeddingProvider]:
    """Return the first available provider, or None for lexical-only mode."""
    candidates = PROVIDERS
    if preferred and preferred != 'auto':
        candidates = [p for p in PROVIDERS if p.name == preferred]
        if not candidates:
            logger.warning("Unknown embedding provider '%s'", preferred)
            return None
    for cls in candidates:
        provider = cls()
        if provider.available():
            logger.info("Embedding provider: %s", provider.name)
            return provider
    logger.info("No embedding provider available - semantic search runs lexical-only")
    return None


class VectorIndex:
    """Cosine-similarity vector store with an on-disk cache."""

    def __init__(self, provider: Optional[EmbeddingProvider] = None):
        self.provider = provider
        self.doc_ids: List[str] = []
        self.vectors: List[List[float]] = []
        self.provider_name: str = provider.name if provider else 'none'

    @property
    def enabled(self) -> bool:
        return bool(self.vectors)

    # ------------------------------------------------------------------
    def build(self, docs: Sequence[Any], cache_path: Optional[Path] = None) -> None:
        if not self.provider:
            return
        cache: Dict[str, List[float]] = {}
        if cache_path and Path(cache_path).exists():
            try:
                cache = json.loads(Path(cache_path).read_text(encoding='utf-8'))
            except Exception:
                cache = {}

        texts, keys, pending_idx = [], [], []
        for doc in docs:
            payload = f"{doc.label} {doc.name} {doc.module} {doc.snippet} {doc.text[:2000]}"
            key = _hash(payload)
            keys.append(key)
            if key not in cache:
                texts.append(payload)
                pending_idx.append(key)

        if texts:
            logger.info("Embedding %s new documents via %s", len(texts), self.provider.name)
            try:
                vectors = self.provider.embed(texts)
            except Exception as exc:  # pragma: no cover - provider/network specific
                logger.warning("Embedding failed (%s) - falling back to lexical-only", exc)
                return
            for key, vec in zip(pending_idx, vectors):
                cache[key] = vec

        self.doc_ids = [d.doc_id for d in docs]
        self.vectors = [self._normalise(cache[k]) for k in keys if k in cache]
        if cache_path:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_path).write_text(json.dumps(cache), encoding='utf-8')

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise(vec: Sequence[float]) -> List[float]:
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def search(self, query: str, top_k: int = 20) -> List[Tuple[str, float]]:
        if not self.enabled or not self.provider:
            return []
        try:
            qvec = self._normalise(self.provider.embed([query])[0])
        except Exception as exc:  # pragma: no cover
            logger.warning("Query embedding failed (%s)", exc)
            return []
        scored = []
        for doc_id, vec in zip(self.doc_ids, self.vectors):
            scored.append((doc_id, sum(a * b for a, b in zip(qvec, vec))))
        scored.sort(key=lambda kv: -kv[1])
        return [(d, round(s, 4)) for d, s in scored[:top_k]]

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {'docIds': self.doc_ids, 'vectors': self.vectors,
                'provider': self.provider_name}

    @staticmethod
    def from_dict(d: Dict[str, Any], provider: Optional[EmbeddingProvider]) -> 'VectorIndex':
        vi = VectorIndex(provider)
        vi.doc_ids = d.get('docIds', [])
        vi.vectors = d.get('vectors', [])
        vi.provider_name = d.get('provider', 'none')
        return vi
