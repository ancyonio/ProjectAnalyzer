"""Git provenance.

Optional: an estate exported from a database rather than checked out of a
repository has no history, and that is not an error. When history is present it
answers the questions a dependency graph alone cannot -- which objects change
most, and who owns the complex ones.

Only commits touching analysed files are recorded, so the graph does not grow
with the history of unrelated parts of a monorepo.
"""
from __future__ import annotations

import logging
import subprocess
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from analyzer_core.ids import commit_id, file_id, slug
from analyzer_core.model import GraphNode

logger = logging.getLogger('oracle_analyzer')

_SEP = '\x1f'
_MAX_COMMITS = 500


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ('git', '-C', str(root)) + args,
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


class GitMetadataMixin:
    """Adds Repository, Branch, Commit and Developer nodes when Git is present."""

    def _parse_git(self) -> int:
        root = self.source_root
        if _git(root, 'rev-parse', '--git-dir') is None:
            logger.info('  no Git repository; skipping history')
            self.stats['commits'] = 0
            return 0

        branch = (_git(root, 'rev-parse', '--abbrev-ref', 'HEAD') or '').strip()
        if branch:
            branch_node = f'branch:{slug(branch)}'
            self._add_node(GraphNode(branch_node, 'Branch', branch, {
                'isCurrent': True,
            }))
            self._add_rel(self.repository_id, branch_node, 'HAS_BRANCH',
                          purpose='repository-branch')

        log = _git(root, 'log', f'-{_MAX_COMMITS}',
                   f'--pretty=format:%H{_SEP}%an{_SEP}%ae{_SEP}%aI{_SEP}%s',
                   '--name-only')
        if not log:
            self.stats['commits'] = 0
            return 0

        analysed = {source.rel_path for source in self.sources}
        commits = 0
        developers: Dict[str, str] = {}
        changes: Counter = Counter()

        for block in log.split('\n\n'):
            lines = [line for line in block.splitlines() if line.strip()]
            if not lines or _SEP not in lines[0]:
                continue
            sha, author, email, when, subject = (lines[0].split(_SEP) + [''] * 5)[:5]
            touched = [path.replace('\\', '/') for path in lines[1:]
                       if path.replace('\\', '/') in analysed]
            if not touched:
                continue

            commit_node = commit_id(sha)
            if commit_node not in self.nodes:
                self._add_node(GraphNode(commit_node, 'Commit', sha[:8], {
                    'sha': sha,
                    'author': author,
                    'authoredAt': when,
                    'subject': subject[:200],
                    'changeCount': len(touched),
                }))
                self._add_rel(self.repository_id, commit_node, 'HAS_COMMIT',
                              purpose='repository-history')
                commits += 1

            dev_node = developers.get(email)
            if dev_node is None:
                dev_node = f'dev:{slug(email or author)}'
                developers[email] = dev_node
                if dev_node not in self.nodes:
                    self._add_node(GraphNode(dev_node, 'Developer', author, {
                        'email': email,
                    }))
            self._add_rel(commit_node, dev_node, 'AUTHORED_BY',
                          purpose='commit-authorship')

            for path in touched:
                node_id = file_id(path)
                if node_id in self.nodes:
                    self._add_rel(commit_node, node_id, 'CHANGED',
                                  purpose='file-history')
                    changes[node_id] += 1

        for node_id, count in changes.items():
            self._set_property(node_id, 'commitCount', count)

        self.stats['commits'] = commits
        self.stats['developers'] = len(developers)
        logger.info('  %d commit(s) touching analysed files, %d author(s)',
                    commits, len(developers))
        return commits
