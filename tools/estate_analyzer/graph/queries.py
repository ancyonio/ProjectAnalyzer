"""Cypher cookbook for the federated graph.

Only questions that need more than one estate to answer. A query that a single
analyzer's cookbook already answers belongs there, not here.
"""
from __future__ import annotations

from typing import Dict, List

from analyzer_core.graph.cookbook import render_cookbook as _render_cookbook
from analyzer_core.graph.cookbook import render_markdown as _render_markdown

TITLE = 'Federated Estate Knowledge Graph'

INTRO = ('Every node carries an `estate` property (`tibco`, `apex`, `oracle`) '
         'and every node contributed by more than one estate carries `estates` '
         'and the `:Federated` label. Inferred cross-estate edges carry '
         '`basis` and `confidence`; filter on them rather than trusting every '
         'edge equally.')

CYPHER_COOKBOOK: List[Dict[str, str]] = [
    {
        'id': 'node-counts-by-estate',
        'title': 'Node counts by estate and label (verification)',
        'purpose': 'Confirm the import populated all three estates.',
        'cypher': 'MATCH (n)\nWHERE n.estate IS NOT NULL\n'
                  'RETURN n.estate AS Estate, labels(n)[0] AS NodeType, '
                  'count(n) AS Count\nORDER BY Estate, Count DESC;',
    },
    {
        'id': 'shared-database-objects',
        'title': 'Database objects contributed by more than one estate',
        'purpose': 'The exact half of the join: these merged on natural key '
                   'alone, with no heuristic.',
        'cypher': 'MATCH (n:Federated)\nWHERE n.estates CONTAINS ";"\n'
                  'RETURN labels(n)[0] AS Label, n.name AS Name, '
                  'n.estates AS Estates\nORDER BY Label, Name;',
    },
    {
        'id': 'contended-tables',
        'title': 'Tables written by more than one estate',
        'purpose': 'The hardest thing in any cutover: two writers on two '
                   'release trains. This is finding XE-001.',
        'cypher': 'MATCH (w)-[r:WRITES_TO|INSERTS_INTO|UPDATES|DELETES_FROM]->'
                  '(t:DbTable)\n'
                  'WITH t, collect(DISTINCT w.estate) AS estates\n'
                  'WHERE size(estates) > 1\n'
                  'RETURN t.name AS Table, estates AS WrittenBy\n'
                  'ORDER BY size(estates) DESC, Table;',
    },
    {
        'id': 'tibco-to-table',
        'title': 'Which TIBCO activity touches a database table',
        'purpose': 'The question the wrapper exists for. Confidence and basis '
                   'come with the answer, because this edge is inferred.',
        'cypher': 'MATCH (p:BWProcess)-[:EXECUTES]->(a:Activity)'
                  '-[r:READS_FROM|WRITES_TO|INSERTS_INTO|UPDATES|DELETES_FROM]->'
                  '(t)\nWHERE t.name = $objectName\n'
                  'RETURN p.name AS Process, a.name AS Activity, type(r) AS Access,\n'
                  '       r.basis AS Basis, r.confidence AS Confidence, '
                  'r.evidence AS Sql\nORDER BY Process, Activity;',
    },
    {
        'id': 'end-to-end-path',
        'title': 'End to end: APEX page to the integration that feeds it',
        'purpose': 'The full chain a change has to survive - user surface, '
                   'data, integration - in one query.',
        'cypher': 'MATCH path = (page:ApexPage)-[*1..4]->(t:DbTable)'
                  '<-[:WRITES_TO|INSERTS_INTO|UPDATES]-(a:Activity)\n'
                  'WHERE page.name = $pageName\n'
                  'RETURN page.name AS Page, t.name AS Table, a.name AS Activity,\n'
                  '       a.module AS TibcoModule\nLIMIT 50;',
    },
    {
        'id': 'blast-radius-across-estates',
        'title': 'Everything that breaks if a table changes, in every estate',
        'purpose': 'A single-estate impact query answers a third of this.',
        'cypher': 'MATCH (t:DbTable {name: $objectName})<-[*1..4]-(n)\n'
                  'WHERE n.estate IS NOT NULL\n'
                  'RETURN DISTINCT n.estate AS Estate, labels(n)[0] AS Label, '
                  'n.name AS Name\nORDER BY Estate, Label, Name;',
    },
    {
        'id': 'inferred-edges',
        'title': 'Every inferred cross-estate edge, weakest first',
        'purpose': 'Audit the join. Anything at confidence 0.5 is a bare-name '
                   'match and should be confirmed by hand.',
        'cypher': 'MATCH (a)-[r]->(b)\nWHERE r.origin = "inferred"\n'
                  'RETURN a.estate AS FromEstate, a.name AS From, type(r) AS Rel,\n'
                  '       b.name AS To, r.basis AS Basis, r.confidence AS Confidence\n'
                  'ORDER BY Confidence ASC, From;',
    },
    {
        'id': 'unmapped-datasources',
        'title': 'JDBC resources with no schema mapping',
        'purpose': 'Everything behind these is missing from the graph. This is '
                   'finding XE-005.',
        'cypher': 'MATCH (r:SharedResource)\n'
                  'WHERE r.resourceType = "JDBC_CONNECTION"\n'
                  '  AND NOT (r)-[:CONNECTS_TO_SCHEMA]->()\n'
                  'RETURN r.name AS Resource, r.module AS Module, r.url AS Url;',
    },
    {
        'id': 'cross-estate-findings',
        'title': 'Findings that only exist across estates',
        'purpose': 'The XE- catalogue, with the recommendation attached.',
        'cypher': 'MATCH (i:Issue)-[:HAS_RECOMMENDATION]->(rec:Recommendation)\n'
                  'WHERE i.ruleId STARTS WITH "XE-"\n'
                  'RETURN i.ruleId AS Rule, i.severity AS Severity, '
                  'i.targetName AS Target,\n       i.description AS Finding, '
                  'rec.text AS Recommendation\nORDER BY Severity DESC, Rule;',
    },
    {
        'id': 'findings-by-estate',
        'title': 'The whole findings ledger, by estate',
        'purpose': 'Rule ids are namespaced (APEX.SEC-001, ORA.SEC-001, XE-001) '
                   'because the same ordinal means different things in '
                   'different dialects.',
        'cypher': 'MATCH (i:Issue)\n'
                  'RETURN i.estate AS Estate, i.category AS Category, '
                  'i.severity AS Severity,\n       count(i) AS Count\n'
                  'ORDER BY Estate, Category, Severity DESC;',
    },
    {
        'id': 'duplicate-statements',
        'title': 'The same statement implemented in two estates',
        'purpose': 'Content-addressed nodes keep their digest, so a duplicate '
                   'is visible rather than merged away. Finding XE-004.',
        'cypher': 'MATCH (s)\nWHERE s.sourceNodeId STARTS WITH "sql:" '
                  'OR s.sourceNodeId STARTS WITH "plsql:"\n'
                  'WITH s.sourceNodeId AS Digest, collect(DISTINCT s.estate) AS estates\n'
                  'WHERE size(estates) > 1\n'
                  'RETURN Digest, estates AS Estates;',
    },
    {
        'id': 'estate-coverage',
        'title': 'What each estate contributed',
        'purpose': 'Quote the weakest input, never an average, when stating '
                   'how complete a federated answer is.',
        'cypher': 'MATCH (e:Estate)-[:CONTAINS_ESTATE]->(root)\n'
                  'RETURN e.name AS Estate, e.title AS Title, '
                  'e.estateNodes AS Nodes,\n       e.sourceRoot AS SourceRoot, '
                  'collect(root.name) AS Roots\nORDER BY Estate;',
    },
]


def render_cookbook() -> str:
    return _render_cookbook(CYPHER_COOKBOOK, TITLE,
                            ':param objectName => "ORDERS"')


def render_markdown() -> str:
    return _render_markdown(CYPHER_COOKBOOK, TITLE, INTRO)
