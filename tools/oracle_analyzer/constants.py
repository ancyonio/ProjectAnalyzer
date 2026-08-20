"""Vocabulary and physical-model configuration for the Oracle analyzer.

One catalogue, consumed by `graph/schema.py`, which turns it into the Neo4j
export schema, the validation configuration and the impact configuration. No
other module constructs those, so the graph, the CI gate and the blast radius
can never disagree about what a label or a relationship means.

The vocabulary deliberately reuses the names `apex_analyzer` already uses for
the database layer (`DbTable`, `READS_FROM`, `HAS_UNIT`, …). A second spelling
for the same concept would split every cross-analyzer query and force two
configurations of the shared engines. The vocabulary is documented for agents
in `.github/skills/oracle-analyst/references/graph-model.md`.
"""
from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

SCHEMA_VERSION = '1.0.0'

# ─────────────────────────────────────────────────────────────
# Labels
# ─────────────────────────────────────────────────────────────
REPO_LABELS: Set[str] = {'Project', 'Repository', 'Branch', 'Commit', 'Developer',
                         'Directory', 'File'}

SCHEMA_OBJECT_LABELS: Set[str] = {
    'DbSchema', 'DbTable', 'DbColumn', 'DbView', 'DbMaterializedView',
    'DbIndex', 'DbConstraint', 'DbSequence', 'DbSynonym', 'DbDatabaseLink',
    'DbType', 'DbTrigger',
}

PROGRAM_LABELS: Set[str] = {'DbPackage', 'PackageSpec', 'PackageBody',
                            'DbProgramUnit', 'PlsqlBlock'}

CODE_LABELS: Set[str] = {'SqlStatement'}

ANALYSIS_LABELS: Set[str] = {'Issue', 'Recommendation', 'CodeMetric',
                             'UnresolvedRef'}

KNOWN_LABELS: Set[str] = (REPO_LABELS | SCHEMA_OBJECT_LABELS | PROGRAM_LABELS
                          | CODE_LABELS | ANALYSIS_LABELS)

# Objects that live in a schema and can be referenced by name from SQL.
DB_OBJECT_LABELS: Set[str] = {
    'DbTable', 'DbView', 'DbMaterializedView', 'DbSequence', 'DbSynonym',
    'DbType', 'DbPackage', 'DbProgramUnit', 'DbTrigger', 'DbDatabaseLink',
}

# ─────────────────────────────────────────────────────────────
# Relationships
# ─────────────────────────────────────────────────────────────
STRUCTURAL_RELS: Set[str] = {
    'CONTAINS_FILE', 'DEFINES', 'OWNS', 'HAS_COLUMN', 'HAS_INDEX',
    'CONSTRAINS', 'HAS_SPEC', 'HAS_BODY', 'HAS_UNIT',
}

DEPENDENCY_RELS: Set[str] = {
    'CALLS', 'DEPENDS_ON', 'RESOLVES_TO', 'USES_SEQUENCE', 'USES_TYPE',
    'REFERENCES_DBLINK',
}

DATA_ACCESS_RELS: Set[str] = {
    'READS_FROM', 'INSERTS_INTO', 'UPDATES', 'DELETES_FROM', 'WRITES_TO',
    'REFERENCES_COLUMN', 'JOINS',
}

RUNTIME_RELS: Set[str] = {'FIRES_ON', 'EXECUTES_SQL', 'EXECUTES_PLSQL'}

ANALYSIS_RELS: Set[str] = {'HAS_ISSUE', 'HAS_RECOMMENDATION', 'AFFECTS',
                           'HAS_METRIC', 'UNRESOLVED'}

GIT_RELS: Set[str] = {'HAS_COMMIT', 'HAS_BRANCH', 'CHANGED', 'AUTHORED_BY'}

KNOWN_REL_TYPES: Set[str] = (STRUCTURAL_RELS | DEPENDENCY_RELS
                             | DATA_ACCESS_RELS | RUNTIME_RELS
                             | ANALYSIS_RELS | GIT_RELS)

# Without these the parse did not do its job.
REQUIRED_REL_TYPES: Set[str] = {'OWNS', 'DEFINES'}

# The specific verb is always emitted alongside the WRITES_TO roll-up, so a
# traversal can use one edge type while lineage uses the precise one.
WRITE_VERBS: Dict[str, str] = {
    'INSERT': 'INSERTS_INTO',
    'UPDATE': 'UPDATES',
    'DELETE': 'DELETES_FROM',
    'MERGE': 'UPDATES',
}

# ─────────────────────────────────────────────────────────────
# Source files
# ─────────────────────────────────────────────────────────────
# Extension -> (object kind hint, is a package half)
SOURCE_EXTENSIONS: Dict[str, str] = {
    '.sql': 'MIXED',
    '.pks': 'PACKAGE_SPEC',
    '.pkb': 'PACKAGE_BODY',
    '.pls': 'MIXED',
    '.plsql': 'MIXED',
    '.prc': 'PROCEDURE',
    '.fnc': 'FUNCTION',
    '.trg': 'TRIGGER',
    '.vw': 'VIEW',
    '.tab': 'TABLE',
    '.typ': 'TYPE',
    '.seq': 'SEQUENCE',
    '.syn': 'SYNONYM',
    '.idx': 'INDEX',
    '.con': 'CONSTRAINT',
    '.ddl': 'MIXED',
    '.pkg': 'MIXED',
}

# Directories that never hold analysable Oracle source.
IGNORED_DIRECTORIES: Set[str] = {
    '.git', '.svn', 'node_modules', 'target', 'build', 'dist', '__pycache__',
    '.idea', '.vscode', 'venv', '.venv',
}

# Anything matching these is deployment plumbing, not application code.
IGNORED_FILE_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r'(^|/)(install|deploy|rollback|grants?)[^/]*\.sql$', re.I),
)

CREDENTIAL_HINTS: Tuple[str, ...] = ('password', 'passwd', 'secret',
                                     'credential', 'apikey', 'api_key', 'token')

# ─────────────────────────────────────────────────────────────
# Impact model
# ─────────────────────────────────────────────────────────────
REL_IMPACT_WEIGHTS: Dict[str, float] = {
    # a caller genuinely breaks when the callee changes
    'CALLS': 1.0,
    'EXECUTES_SQL': 0.95,
    'EXECUTES_PLSQL': 0.95,
    # data access: a column change reaches everything that reads it
    'READS_FROM': 0.9,
    'WRITES_TO': 0.9,
    'INSERTS_INTO': 0.9,
    'UPDATES': 0.9,
    'DELETES_FROM': 0.9,
    'REFERENCES_COLUMN': 0.7,
    # A join says two tables are queried together, which is a weaker signal
    # than reading one: the shape of the query changes, the data does not.
    'JOINS': 0.4,
    # declared dependencies
    'DEPENDS_ON': 0.85,
    'FIRES_ON': 0.9,
    'RESOLVES_TO': 0.8,
    'USES_SEQUENCE': 0.5,
    'USES_TYPE': 0.7,
    'REFERENCES_DBLINK': 0.4,
    # structure
    'HAS_COLUMN': 0.6,
    'CONSTRAINS': 0.5,
    'HAS_INDEX': 0.3,
    'HAS_SPEC': 0.9,
    'HAS_BODY': 0.4,
}

# Structure is not a dependency path. Traversing HAS_UNIT would make every
# unit in a package look reachable from any one of them, which turns a
# single-procedure change into a whole-package blast radius.
IMPACT_EXCLUDED_RELS: Set[str] = {
    'OWNS', 'CONTAINS_FILE', 'DEFINES', 'HAS_UNIT', 'HAS_COMMIT', 'HAS_BRANCH',
    'CHANGED', 'AUTHORED_BY', 'HAS_ISSUE', 'AFFECTS', 'HAS_RECOMMENDATION',
    'HAS_METRIC', 'UNRESOLVED',
}

MULTIPLIERS: Dict[str, float] = {
    'DbTable': 2.0, 'DbView': 2.0, 'DbMaterializedView': 2.0,
    'DbPackage': 2.0, 'PackageSpec': 2.2, 'PackageBody': 1.2,
    'DbProgramUnit': 1.5, 'DbTrigger': 1.5,
    'SqlStatement': 0.8, 'PlsqlBlock': 0.8, 'DbColumn': 0.3,
    'DbSequence': 0.4, 'DbSynonym': 0.5, 'DbType': 1.0,
    'File': 0.2, 'Issue': 0.0, 'Recommendation': 0.0, 'CodeMetric': 0.0,
}

# ─────────────────────────────────────────────────────────────
# Physical model
# ─────────────────────────────────────────────────────────────
INT_FIELDS: Set[str] = {
    'lineStart', 'lineEnd', 'loc', 'lineCount', 'unitCount', 'columnCount',
    'tableCount', 'bindCount', 'callCount', 'statementCount', 'argumentCount',
    'overload', 'columnId', 'dataLength', 'numRows', 'specLines', 'bodyLines',
    'sourceLine', 'fanIn', 'fanOut', 'commitCount', 'changeCount',
    'dynamicSqlSites', 'position', 'branchCount', 'loopCount', 'joinCount',
    'referenceCount', 'depth',
}

FLOAT_FIELDS: Set[str] = {'complexity', 'complexityScore', 'confidence', 'value'}

BOOL_FIELDS: Set[str] = {
    'hasSelectStar', 'hasHint', 'hasDbLink', 'hasDynamicSql', 'hasCommit',
    'hasExceptionHandler', 'hasWhenOthersNull', 'isStandalone', 'isPk', 'isFk',
    'nullable', 'isPublic', 'ambiguous', 'inferred', 'isDeterministic',
    'hasNoWhere', 'isPipelined', 'hasPk', 'isDefault', 'isPublished',
    'declaredOnly', 'hasQuery', 'isDynamic', 'partitioned',
}

COMPOSITE_CONSTRAINTS: List[Tuple[str, List[str]]] = [
    ('DbColumn', ['owner', 'tableName', 'name']),
    ('DbProgramUnit', ['owner', 'packageName', 'name', 'overload']),
]

SECONDARY_INDEXES: List[Tuple[str, List[str]]] = [
    ('DbTable', ['owner']),
    ('DbView', ['owner']),
    ('DbPackage', ['owner']),
    ('DbProgramUnit', ['owner']),
    ('DbProgramUnit', ['unitType']),
    ('DbProgramUnit', ['packageName']),
    ('DbColumn', ['tableName']),
    ('SqlStatement', ['verb']),
    ('Issue', ['ruleId']),
    ('Issue', ['severity']),
    ('File', ['filePath']),
]

FULLTEXT_INDEXES: List[Tuple[str, List[str], List[str]]] = [
    ('oracle_code_ft', ['SqlStatement', 'PlsqlBlock'], ['text']),
    ('oracle_name_ft', ['DbTable', 'DbView', 'DbPackage', 'DbProgramUnit',
                        'DbTrigger', 'DbType'], ['name']),
]

# Objects that legitimately stand alone: an index or a sequence that nothing
# in the analysed tree references is a finding for the rules engine, not a
# structural defect for the validator.
ORPHAN_TOLERANT_LABELS: Set[str] = {
    'DbIndex', 'DbConstraint', 'DbSequence', 'DbType', 'DbDatabaseLink',
    'DbSynonym', 'Repository', 'Branch', 'Commit', 'Developer', 'Directory',
    'CodeMetric', 'UnresolvedRef', 'Project',
}

ID_PATTERN = re.compile(r'^[A-Za-z0-9_.:#$/@ -]+$')

# ─────────────────────────────────────────────────────────────
# Complexity
# ─────────────────────────────────────────────────────────────
COMPLEXITY_WEIGHTS: Dict[str, float] = {
    'loc': 0.05,
    'statementCount': 1.0,
    'callCount': 0.8,
    'branchCount': 0.6,
    'loopCount': 0.8,
    'dynamicSql': 5.0,
}

TIER_THRESHOLDS: Tuple[Tuple[float, str], ...] = (
    (40.0, 'Critical'), (20.0, 'High'), (8.0, 'Medium'), (0.0, 'Low'),
)


def tier_for(score: float) -> str:
    for threshold, name in TIER_THRESHOLDS:
        if score > threshold:
            return name
    return 'Low'


SEVERITY_ORDER: List[str] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
