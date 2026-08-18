"""Search engine: hybrid lexical + vector retrieval with graph context.

A search hit is not just "this file matched". Every result carries its graph
neighbourhood — who calls it, which schemas it uses, which entry points
reach it — so the answer to *"where is X implemented?"* comes with the
answer to *"and what happens if I change it?"* attached.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..model import Graph
from .corpus import CorpusBuilder, Document
from .embed import VectorIndex, resolve_provider
from .lexical import BM25Index

logger = logging.getLogger('tibco_analyzer')

INDEX_FILE = 'search_index.json'
VECTOR_FILE = 'search_vectors.json'
EMBED_CACHE = 'embedding_cache.json'
RRF_K = 60.0


class SearchEngine:
    """Builds, persists and queries the artefact index."""

    def __init__(self, graph: Graph, index_dir: Path,
                 tibco_root: Optional[Path] = None,
                 embedding_provider: Optional[str] = 'auto'):
        self.graph = graph
        self.index_dir = Path(index_dir)
        self.tibco_root = Path(tibco_root) if tibco_root else None
        self.embedding_provider_name = embedding_provider
        self.documents: Dict[str, Document] = {}
        self.bm25 = BM25Index()
        self.vectors: Optional[VectorIndex] = None

    # ------------------------------------------------------------------
    def build(self, use_embeddings: bool = True) -> Dict[str, Any]:
        docs = CorpusBuilder(self.graph, self.tibco_root).build()
        self.documents = {d.doc_id: d for d in docs}
        self.bm25 = BM25Index()
        self.bm25.add_documents(docs)

        provider = resolve_provider(self.embedding_provider_name) if use_embeddings else None
        self.vectors = VectorIndex(provider)
        if provider:
            self.vectors.build(docs, self.index_dir / EMBED_CACHE)

        self.index_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            'documents': [d.to_dict() for d in docs],
            'bm25': self.bm25.to_dict(),
        }
        (self.index_dir / INDEX_FILE).write_text(
            json.dumps(payload), encoding='utf-8')
        (self.index_dir / VECTOR_FILE).write_text(
            json.dumps(self.vectors.to_dict()), encoding='utf-8')

        return {
            'documents': len(docs),
            'labels': sorted({d.label for d in docs}),
            'vectorSearch': bool(self.vectors and self.vectors.enabled),
            'embeddingProvider': self.vectors.provider_name if self.vectors else 'none',
            'indexDir': str(self.index_dir),
        }

    # ------------------------------------------------------------------
    def load(self) -> None:
        index_path = self.index_dir / INDEX_FILE
        if not index_path.exists():
            raise FileNotFoundError(
                f"Search index not found at {index_path}. Run `tibco-analyze index` first."
            )
        payload = json.loads(index_path.read_text(encoding='utf-8'))
        self.documents = {d['docId']: Document.from_dict(d) for d in payload['documents']}
        self.bm25 = BM25Index.from_dict(payload['bm25'])

        vec_path = self.index_dir / VECTOR_FILE
        if vec_path.exists():
            data = json.loads(vec_path.read_text(encoding='utf-8'))
            provider = None
            if data.get('vectors'):
                provider = resolve_provider(self.embedding_provider_name)
            self.vectors = VectorIndex.from_dict(data, provider)

    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int = 10,
               labels: Optional[Sequence[str]] = None,
               modules: Optional[Sequence[str]] = None,
               with_context: bool = True) -> Dict[str, Any]:
        lexical = self.bm25.search(query, top_k=top_k * 5)
        vector = self.vectors.search(query, top_k=top_k * 5) if (
            self.vectors and self.vectors.enabled) else []

        fused: Dict[str, Dict[str, Any]] = {}
        for rank, (doc_id, score, matched) in enumerate(lexical, 1):
            fused.setdefault(doc_id, {'rrf': 0.0, 'matched': matched,
                                      'lexical': score, 'vector': None})
            fused[doc_id]['rrf'] += 1.0 / (RRF_K + rank)
        for rank, (doc_id, score) in enumerate(vector, 1):
            entry = fused.setdefault(doc_id, {'rrf': 0.0, 'matched': [],
                                              'lexical': None, 'vector': None})
            entry['rrf'] += 1.0 / (RRF_K + rank)
            entry['vector'] = score

        label_filter = set(labels) if labels else None
        module_filter = set(modules) if modules else None

        results: List[Dict[str, Any]] = []
        for doc_id, info in sorted(fused.items(), key=lambda kv: -kv[1]['rrf']):
            doc = self.documents.get(doc_id)
            if doc is None:
                continue
            if label_filter and doc.label not in label_filter:
                continue
            if module_filter and doc.module not in module_filter:
                continue
            row = {
                'rank': len(results) + 1,
                'score': round(info['rrf'], 6),
                'lexicalScore': info['lexical'],
                'vectorScore': info['vector'],
                'matchedTerms': info['matched'],
                'label': doc.label,
                'name': doc.name,
                'nodeId': doc.node_id,
                'module': doc.module,
                'filePath': doc.file_path,
                'summary': doc.snippet,
            }
            if with_context:
                row['graphContext'] = self._context(doc.node_id)
            results.append(row)
            if len(results) >= top_k:
                break

        return {
            'query': query,
            'mode': 'hybrid' if vector else 'lexical',
            'embeddingProvider': self.vectors.provider_name if self.vectors else 'none',
            'filters': {'labels': list(labels or []), 'modules': list(modules or [])},
            'totalCandidates': len(fused),
            'results': results,
        }

    # ------------------------------------------------------------------
    def _context(self, node_id: str) -> Dict[str, Any]:
        """The graph neighbourhood that makes a hit actionable."""
        node = self.graph.node(node_id)
        if node is None:
            return {}
        out, inn = self.graph.outgoing(node_id), self.graph.incoming(node_id)

        def names(rels, side: str, label: Optional[str] = None) -> List[str]:
            vals = []
            for r in rels:
                other = self.graph.node(r.end_id if side == 'out' else r.start_id)
                if other and (label is None or other.label == label):
                    vals.append(other.name)
            return sorted(set(vals))

        owner = ''
        if node.label == 'Activity':
            proc = self.graph.node(str(node.properties.get('processRef', '')))
            owner = proc.name if proc else ''
        elif node.label == 'Element':
            xsd = self.graph.node(str(node.properties.get('schemaRef', '')))
            owner = xsd.name if xsd else ''

        return {
            'ownedBy': owner,
            'entryType': node.properties.get('entryType', ''),
            'tier': node.properties.get('tier', ''),
            'usesSchemas': names([r for r in out if r.rel_type == 'USES_XSD'], 'out'),
            'calls': names([r for r in out if r.rel_type in ('CALLS', 'CALLS_EXTERNAL')], 'out'),
            'usedBy': names([r for r in inn if r.rel_type in
                             ('USES_XSD', 'CALLS', 'REFERENCES', 'IMPORTS_SCHEMA')], 'in'),
            'activities': names([r for r in out if r.rel_type == 'EXECUTES'], 'out')[:15],
            'springTargets': sorted({
                str(self.graph.nodes[r.end_id].properties.get('springEquivalent', ''))
                for r in out if r.rel_type == 'EXECUTES' and r.end_id in self.graph.nodes
                and self.graph.nodes[r.end_id].properties.get('springEquivalent')
            }),
            'degree': self.graph.degree(node_id),
        }


def render_markdown(result: Dict[str, Any]) -> str:
    lines = [
        f"# Search: \"{result['query']}\"",
        '',
        f"Mode: **{result['mode']}** (embeddings: {result['embeddingProvider']}) | "
        f"candidates: {result['totalCandidates']} | shown: {len(result['results'])}",
        '',
    ]
    if not result['results']:
        lines.append('No matches. Try broader terms, or re-run `index` if the graph changed.')
        return '\n'.join(lines)

    for row in result['results']:
        lines.append(f"## {row['rank']}. {row['label']}: {row['name']}")
        lines.append('')
        lines.append(f"- **File:** `{row['filePath'] or 'n/a'}`")
        lines.append(f"- **Module:** {row['module'] or 'n/a'} | **Node:** `{row['nodeId']}`")
        lines.append(f"- **Why:** {row['summary']}")
        if row['matchedTerms']:
            lines.append(f"- **Matched terms:** {', '.join(row['matchedTerms'])}")
        ctx = row.get('graphContext') or {}
        if ctx.get('ownedBy'):
            lines.append(f"- **Defined in:** {ctx['ownedBy']}")
        if ctx.get('entryType') and ctx['entryType'] != 'NONE':
            lines.append(f"- **Entry point:** {ctx['entryType']}")
        if ctx.get('usesSchemas'):
            lines.append(f"- **Uses schemas:** {', '.join(ctx['usesSchemas'][:8])}")
        if ctx.get('calls'):
            lines.append(f"- **Calls:** {', '.join(ctx['calls'][:8])}")
        if ctx.get('usedBy'):
            lines.append(f"- **Used by:** {', '.join(ctx['usedBy'][:8])}")
        if ctx.get('springTargets'):
            lines.append(f"- **Spring targets:** {', '.join(ctx['springTargets'][:8])}")
        lines.append('')
    lines.append('> Next: `tibco-analyze impact --target "<Label>:<Name>"` for the blast radius '
                 'of changing any hit above.')
    return '\n'.join(lines)
