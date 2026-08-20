"""Repository and change layer.

Adds `:Repository`, `:Branch`, `:Commit` and `CHANGED` edges from `git log`,
so the graph can answer "what APEX functionality changed in this release, and
which database objects does that reach". Only meaningful for a split export,
where each component owns a file.

Entirely optional: when the source tree is not a git repository, or git is not
on PATH, the layer is skipped and the reason recorded rather than failing the
analysis.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from analyzer_core.ids import commit_id, file_id, repository_id

logger = logging.getLogger('apex_analyzer')

_FORMAT = '%H%x1f%an%x1f%ae%x1f%aI%x1f%s'
_MAX_COMMITS = 500


def _run(args: List[str], cwd: Path) -> Optional[str]:
    try:
        completed = subprocess.run(args, cwd=str(cwd), capture_output=True,
                                   text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


class GitMetadataMixin:

    def _parse_git_metadata(self) -> None:
        if not self.git_range and not self.git_enabled:
            return
        root = self.source_root
        if _run(['git', 'rev-parse', '--is-inside-work-tree'], root) is None:
            self.stats['gitSkipped'] = 1
            self.export_meta['gitStatus'] = 'not a git repository (or git unavailable)'
            return

        remote = (_run(['git', 'config', '--get', 'remote.origin.url'], root) or '').strip()
        branch = (_run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], root) or '').strip()
        head = (_run(['git', 'rev-parse', 'HEAD'], root) or '').strip()
        repo_name = remote.rstrip('/').rsplit('/', 1)[-1] or root.name

        repo_node = repository_id(repo_name)
        self._node(repo_node, 'Repository', repo_name,
                   {'remote': remote, 'defaultBranch': branch})
        branch_node = f'branch:{repo_name}:{branch or "HEAD"}'
        self._node(branch_node, 'Branch', branch or 'HEAD', {'headSha': head})
        self._rel(repo_node, branch_node, 'HAS_BRANCH')

        # `git log` reports paths from the repository root, while `File` nodes
        # are keyed relative to the analysed root. Those coincide only when the
        # export sits at the top of the repository; anywhere else every path
        # misses and the layer silently records no changes at all.
        prefix = (_run(['git', 'rev-parse', '--show-prefix'], root) or '').strip()
        prefix = prefix.replace('\\', '/')
        if prefix and not prefix.endswith('/'):
            prefix += '/'

        args = ['git', 'log', f'--format={_FORMAT}', '--name-status',
                f'--max-count={_MAX_COMMITS}']
        if self.git_range:
            args.append(self.git_range)
        # Confine the log to the analysed subtree so the commit budget is spent
        # on relevant history rather than on the rest of a monorepo.
        args += ['--', '.']
        output = _run(args, root)
        if output is None:
            self.export_meta['gitStatus'] = f'git log failed for range {self.git_range}'
            return

        current: Optional[str] = None
        commits = 0
        for line in output.splitlines():
            if '\x1f' in line:
                sha, author, email, when, subject = (line.split('\x1f') + [''] * 5)[:5]
                current = commit_id(sha)
                self._node(current, 'Commit', sha[:12], {
                    'sha': sha, 'author': author, 'authorEmail': email,
                    'committedAt': when, 'subject': subject})
                self._rel(branch_node, current, 'HAS_COMMIT')
                commits += 1
                continue
            if not line.strip() or current is None:
                continue
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            status, path = parts[0].strip(), parts[-1].strip()
            path = path.replace('\\', '/')
            if prefix:
                if not path.startswith(prefix):
                    continue                  # outside the analysed subtree
                path = path[len(prefix):]
            node_id = file_id(path)
            if node_id in self.nodes:
                self._rel(current, node_id, 'CHANGED', changeType=status[:1])
        self.stats['gitCommits'] = commits
        self.export_meta['gitStatus'] = f'{commits} commit(s) recorded'
        self.export_meta['gitRange'] = self.git_range or 'HEAD'
