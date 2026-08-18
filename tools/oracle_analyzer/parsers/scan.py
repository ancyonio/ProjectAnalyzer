"""Source discovery.

Walks the repository, classifies each file by extension and content, and
creates the `File` and `Directory` nodes everything else hangs provenance off.
Reading happens once here; every later pass works from the cached text so a
large estate is not read from disk repeatedly.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from analyzer_core.ids import file_id
from analyzer_core.model import GraphNode
from analyzer_core.utils import read_text, sha1_16

from ..constants import (IGNORED_DIRECTORIES, IGNORED_FILE_PATTERNS,
                         SOURCE_EXTENSIONS)

logger = logging.getLogger('oracle_analyzer')

# Enough of the file to classify it without holding the whole estate twice.
_SNIFF_BYTES = 4000


@dataclass
class SourceFile:
    """One analysable file, read once."""
    path: Path
    rel_path: str
    kind: str
    text: str
    node_id: str = ''
    line_count: int = 0
    source_hash: str = ''
    objects: List[str] = field(default_factory=list)


def _looks_like_oracle(text: str) -> bool:
    """A `.sql` file that creates nothing is a script, not a definition."""
    head = text[:_SNIFF_BYTES].lower()
    return any(token in head for token in (
        'create or replace', 'create table', 'create view', 'create index',
        'create sequence', 'create synonym', 'create trigger', 'create type',
        'create materialized', 'create package', 'create global temporary',
        'alter table', 'declare', 'begin'))


class SourceScanMixin:
    """Discovers and reads the Oracle source tree."""

    def _scan_sources(self) -> int:
        files: List[SourceFile] = []
        skipped: Counter = Counter()

        for path in sorted(self.source_root.rglob('*')):
            if not path.is_file():
                continue
            rel = path.relative_to(self.source_root)
            parts = set(rel.parts[:-1])
            if parts & IGNORED_DIRECTORIES:
                skipped['ignored-directory'] += 1
                continue

            rel_path = str(rel).replace('\\', '/')
            suffix = path.suffix.lower()
            self.file_counts[suffix or '(none)'] += 1

            kind = SOURCE_EXTENSIONS.get(suffix)
            if kind is None:
                skipped['not-oracle-source'] += 1
                continue
            if any(pattern.search(rel_path) for pattern in IGNORED_FILE_PATTERNS):
                skipped['deployment-script'] += 1
                continue

            text = read_text(path)
            if not text or not text.strip():
                skipped['empty'] += 1
                continue
            if kind == 'MIXED' and not _looks_like_oracle(text):
                skipped['no-ddl-content'] += 1
                continue

            source = SourceFile(
                path=path,
                rel_path=rel_path,
                kind=kind,
                text=text,
                line_count=text.count('\n') + 1,
                source_hash=sha1_16(text),
            )
            source.node_id = file_id(rel_path)
            files.append(source)

        self.sources = files
        self.stats['files_scanned'] = len(files)
        self.stats['files_skipped'] = sum(skipped.values())
        self.skipped_files = dict(skipped)

        self._create_file_nodes(files)
        logger.info('  %d source file(s), %d skipped', len(files), sum(skipped.values()))
        return len(files)

    # ------------------------------------------------------------------
    def _create_file_nodes(self, files: List[SourceFile]) -> None:
        directories: Dict[str, str] = {}

        for source in files:
            self._add_node(GraphNode(source.node_id, 'File', Path(source.rel_path).name, {
                'filePath': source.rel_path,
                'kind': source.kind,
                'loc': source.line_count,
                'sourceHash': source.source_hash,
                'extension': source.path.suffix.lower(),
            }))
            self._add_rel(self.repository_id, source.node_id, 'CONTAINS_FILE',
                          purpose='repository-membership')

            folder = str(Path(source.rel_path).parent).replace('\\', '/')
            if folder in ('', '.'):
                continue
            if folder not in directories:
                dir_node = f'dir:{folder}'
                directories[folder] = dir_node
                self._add_node(GraphNode(dir_node, 'Directory', Path(folder).name, {
                    'filePath': folder,
                    'depth': len(Path(folder).parts),
                }))
                self._add_rel(self.repository_id, dir_node, 'CONTAINS_FILE',
                              purpose='repository-membership')
            self._add_rel(directories[folder], source.node_id, 'CONTAINS_FILE',
                          purpose='directory-membership')

    # ------------------------------------------------------------------
    def source_by_id(self, node_id: str) -> Optional[SourceFile]:
        for source in self.sources:
            if source.node_id == node_id:
                return source
        return None
