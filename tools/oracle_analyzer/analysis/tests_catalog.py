"""The test layer.

`TestCase` is populated from utPLSQL annotations, which are the one statement of
test intent an Oracle repository actually carries: `--%suite` marks a package as
a suite and `--%test` marks the declaration that follows it as a case. Both are
read from the scanned source, so nothing is inferred from a name.

Annotations live in the package spec, next to the declaration they describe, so
the mapping is positional: a `--%test` applies to the next `procedure` or
`function` declared after it. That is how utPLSQL itself reads them.

What a case covers is taken from what it calls. A utPLSQL case exercises
production code by calling it, so `HAS_TEST` runs from each production unit the
case reaches to the case itself -- the direction the question is asked in
("what covers this procedure?"). Units inside a suite are excluded from their
own coverage, or every case would appear to test its own setup.

A case that calls nothing the analyzer could resolve is still recorded, with
`coversCount: 0`. An untraceable test is a visible gap; omitting it would make
the suite look smaller than it is.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Set, Tuple

from analyzer_core.model import GraphNode

logger = logging.getLogger('oracle_analyzer')

_SUITE_RE = re.compile(r'--\s*%suite\b', re.IGNORECASE)
_SUITEPATH_RE = re.compile(r'--\s*%suitepath\s*\(\s*([\w.]+)\s*\)', re.IGNORECASE)
# `--%test` optionally carries a display name: `--%test(creates a customer)`.
_TEST_RE = re.compile(r'--\s*%test\b\s*(?:\(\s*(.*?)\s*\))?', re.IGNORECASE)
_DECL_RE = re.compile(r'\b(?:procedure|function)\s+("?[\w$#]+"?)', re.IGNORECASE)
_PACKAGE_RE = re.compile(
    r'\bcreate\s+(?:or\s+replace\s+)?(?:editionable\s+)?package\s+(?:body\s+)?'
    r'([\w$#."]+)', re.IGNORECASE)


def attach_tests(analyzer) -> int:
    """Create `TestCase` nodes and `HAS_TEST` edges. Returns cases created."""
    suites: Dict[str, str] = {}
    cases: Dict[Tuple[str, str], str] = {}      # (package, unit) -> display name

    for source in analyzer.sources:
        if not _SUITE_RE.search(source.text):
            continue
        package = _package_of(source.text)
        if not package:
            continue
        path = _SUITEPATH_RE.search(source.text)
        suites[package] = path.group(1) if path else suites.get(package, '')
        for unit_name, display in _annotated_units(source.text):
            cases[(package, unit_name)] = display

    if not suites:
        analyzer.stats['test_cases'] = 0
        logger.info('  no utPLSQL suites found')
        return 0

    created = 0
    for unit in sorted(analyzer.nodes.values(), key=lambda n: n.node_id):
        if unit.label != 'DbProgramUnit':
            continue
        package = str(unit.properties.get('packageName') or '').upper()
        key = (package, unit.name.upper())
        if key not in cases:
            continue

        covers = _covered_units(analyzer, unit.node_id, suites)
        case_node = f'test:{unit.node_id.split(":", 1)[-1]}'
        if case_node not in analyzer.nodes:
            analyzer._add_node(GraphNode(case_node, 'TestCase', unit.name, {
                'framework': 'utPLSQL',
                'suite': package,
                'suitePath': suites.get(package, ''),
                'displayName': cases[key] or unit.name,
                'filePath': unit.properties.get('filePath', ''),
                'lineStart': unit.properties.get('lineStart', 0),
                'lineEnd': unit.properties.get('lineEnd', 0),
                'language': 'PLSQL',
                'coversCount': len(covers),
                'origin': 'ddl',
            }))
            created += 1
        for target in covers:
            analyzer._add_rel(target, case_node, 'HAS_TEST',
                              purpose='test-coverage')

    analyzer.stats['test_cases'] = created
    logger.info('  %d utPLSQL test case(s) across %d suite(s)',
                created, len(suites))
    return created


def _package_of(text: str) -> str:
    match = _PACKAGE_RE.search(text)
    if not match:
        return ''
    name = match.group(1).strip('"')
    return name.rsplit('.', 1)[-1].strip('"').upper()


def _annotated_units(text: str) -> List[Tuple[str, str]]:
    """`--%test` annotations paired with the declaration each precedes."""
    out: List[Tuple[str, str]] = []
    for match in _TEST_RE.finditer(text):
        declaration = _DECL_RE.search(text, match.end())
        if declaration is None:
            continue
        out.append((declaration.group(1).strip('"').upper(),
                    (match.group(1) or '').strip('\'" ')))
    return out


def _covered_units(analyzer, case_unit_id: str,
                   suites: Dict[str, str]) -> List[str]:
    """Production units the case calls. Units inside a suite do not count."""
    covered: Set[str] = set()
    for rel in analyzer.rels:
        if rel.rel_type != 'CALLS' or rel.start_id != case_unit_id:
            continue
        target = analyzer.nodes.get(rel.end_id)
        if target is None or target.label != 'DbProgramUnit':
            continue
        if str(target.properties.get('packageName') or '').upper() in suites:
            continue
        covered.add(target.node_id)
    return sorted(covered)
