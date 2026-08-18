"""Export discovery and file classification.

Works out what kind of APEX export it has been pointed at and what every file
in it is, so the rest of the parser never guesses:

    split export      f100/application/pages/page_00010.sql, …
    single file       f100.sql
    readable export   f100/readable/application/**.yaml   (recorded, not parsed)
    database DDL      create table / package body scripts committed alongside

Classification is by content first (does the file call the APEX import API?)
and by path second, because a repository can lay its export out any way it
likes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from analyzer_core.ids import file_id
from analyzer_core.utils import read_text, rel_path, sha1_full

SCAN_EXCLUDE_DIRS = {'.git', '.svn', 'node_modules', '__pycache__', '.idea',
                     'target', 'build', '.settings', 'dist'}

APEX_API_RE = re.compile(r'wwv_flow_(?:api|imp)[a-z_]*\s*\.', re.IGNORECASE)
PACKAGE_BODY_RE = re.compile(r'create\s+(or\s+replace\s+)?package\s+body', re.IGNORECASE)
PACKAGE_SPEC_RE = re.compile(r'create\s+(or\s+replace\s+)?package\s+(?!body)', re.IGNORECASE)
DDL_RE = re.compile(
    r'create\s+(or\s+replace\s+)?(table|view|materialized\s+view|sequence|'
    r'synonym|trigger|type|index)\b', re.IGNORECASE)
STANDALONE_UNIT_RE = re.compile(
    r'create\s+(or\s+replace\s+)?(procedure|function)\s+', re.IGNORECASE)
APP_ID_RE = re.compile(r"p_default_application_id\s*=>\s*(\d+)", re.IGNORECASE)
FLOW_ID_RE = re.compile(r"create_flow\s*\(\s*[^)]*?p_id\s*=>\s*(\d+)",
                        re.IGNORECASE | re.DOTALL)
PAGE_FILE_RE = re.compile(r'page_(\d+)\.sql$', re.IGNORECASE)

KIND_APEX_PAGE = 'APEX_PAGE_EXPORT'
KIND_APEX_SHARED = 'APEX_SHARED_COMPONENT'
KIND_APEX_APP = 'APEX_APP_EXPORT'
KIND_INSTALL = 'INSTALL_SCRIPT'
KIND_PACKAGE_SPEC = 'PACKAGE_SPEC'
KIND_PACKAGE_BODY = 'PACKAGE_BODY'
KIND_DDL = 'DDL'
KIND_SQL = 'SQL_SCRIPT'
KIND_READABLE = 'APEX_READABLE_EXPORT'
KIND_OTHER = 'OTHER'

APEX_KINDS = {KIND_APEX_PAGE, KIND_APEX_SHARED, KIND_APEX_APP}
DB_KINDS = {KIND_PACKAGE_SPEC, KIND_PACKAGE_BODY, KIND_DDL}


@dataclass
class ExportFile:
    path: Path
    relative: str
    kind: str
    size: int
    sha1: str
    page_id: Optional[int] = None

    @property
    def node_id(self) -> str:
        return file_id(self.relative)


@dataclass
class ExportInventory:
    root: Path
    files: List[ExportFile] = field(default_factory=list)
    mode: str = 'unknown'
    application_ids: List[int] = field(default_factory=list)
    readable_files: int = 0
    counts: Dict[str, int] = field(default_factory=dict)

    def of_kind(self, *kinds: str) -> List[ExportFile]:
        wanted = set(kinds)
        return [f for f in self.files if f.kind in wanted]

    @property
    def apex_files(self) -> List[ExportFile]:
        return self.of_kind(*APEX_KINDS)

    @property
    def db_files(self) -> List[ExportFile]:
        return self.of_kind(*DB_KINDS)


def _classify(path: Path, relative: str, head: str) -> str:
    lowered = relative.lower()
    if '/readable/' in lowered or lowered.endswith(('.yaml', '.yml')):
        return KIND_READABLE
    if APEX_API_RE.search(head):
        if '/pages/' in lowered or PAGE_FILE_RE.search(lowered):
            return KIND_APEX_PAGE
        if '/shared_components/' in lowered or '/user_interface/' in lowered:
            return KIND_APEX_SHARED
        return KIND_APEX_APP
    if path.name.lower() in ('install.sql', 'set_environment.sql', 'end_environment.sql'):
        return KIND_INSTALL
    if PACKAGE_BODY_RE.search(head):
        return KIND_PACKAGE_BODY
    if PACKAGE_SPEC_RE.search(head) or STANDALONE_UNIT_RE.search(head):
        return KIND_PACKAGE_SPEC
    if DDL_RE.search(head):
        return KIND_DDL
    if lowered.endswith('.sql'):
        return KIND_SQL
    return KIND_OTHER


def discover(root: Path) -> ExportInventory:
    """Walk `root` and classify every file that could carry APEX or DB facts."""
    root = Path(root).resolve()
    if not root.exists():
        raise FileNotFoundError(f'APEX source directory not found: {root}')

    inventory = ExportInventory(root=root)
    application_ids: List[int] = []

    paths = [root] if root.is_file() else sorted(root.rglob('*'))
    for path in paths:
        if not path.is_file():
            continue
        if any(part in SCAN_EXCLUDE_DIRS for part in path.parts):
            continue
        suffix = path.suffix.lower()
        if suffix not in ('.sql', '.pks', '.pkb', '.plb', '.yaml', '.yml'):
            continue
        relative = rel_path(path, root if root.is_dir() else root.parent)
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        head = read_text(path, limit=8192)
        kind = _classify(path, relative, head)
        page_match = PAGE_FILE_RE.search(path.name)
        export_file = ExportFile(
            path=path, relative=relative, kind=kind, size=len(raw),
            sha1=sha1_full(raw),
            page_id=int(page_match.group(1)) if page_match else None)
        inventory.files.append(export_file)
        if kind == KIND_READABLE:
            inventory.readable_files += 1
        if kind in APEX_KINDS:
            for match in APP_ID_RE.finditer(head):
                application_ids.append(int(match.group(1)))
            for match in FLOW_ID_RE.finditer(head):
                application_ids.append(int(match.group(1)))

    counts: Dict[str, int] = {}
    for export_file in inventory.files:
        counts[export_file.kind] = counts.get(export_file.kind, 0) + 1
    inventory.counts = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    inventory.application_ids = sorted(set(application_ids))

    page_files = len(inventory.of_kind(KIND_APEX_PAGE))
    app_files = len(inventory.of_kind(KIND_APEX_APP))
    if page_files > 1:
        inventory.mode = 'split'
    elif app_files == 1 and page_files <= 1:
        inventory.mode = 'single'
    elif inventory.readable_files and not inventory.apex_files:
        inventory.mode = 'readable'
    elif inventory.apex_files:
        inventory.mode = 'split'
    else:
        inventory.mode = 'database-only'
    return inventory
