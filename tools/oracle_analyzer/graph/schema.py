"""Physical and logical schema wiring.

The one place that turns the constants catalogue into the objects the core
engines need. Nothing else in the package constructs these, so the export, the
CI gate and the blast radius can never disagree about the vocabulary.
"""
from __future__ import annotations

from analyzer_core.analysis.impact import ImpactConfig
from analyzer_core.graph.exporters import Neo4jSchema
from analyzer_core.graph.validate import ValidationConfig
from analyzer_core.model import GraphNode

from ..constants import (BOOL_FIELDS, COMPOSITE_CONSTRAINTS, FLOAT_FIELDS,
                         FULLTEXT_INDEXES, ID_PATTERN, IMPACT_EXCLUDED_RELS,
                         INT_FIELDS, KNOWN_LABELS, KNOWN_REL_TYPES, MULTIPLIERS,
                         ORPHAN_TOLERANT_LABELS, REL_IMPACT_WEIGHTS,
                         REQUIRED_REL_TYPES, SECONDARY_INDEXES)
from .validate_rules import ORACLE_RULES


def neo4j_schema() -> Neo4jSchema:
    return Neo4jSchema(
        title='Oracle PL/SQL Knowledge Graph',
        int_fields=set(INT_FIELDS),
        float_fields=set(FLOAT_FIELDS),
        bool_fields=set(BOOL_FIELDS),
        composite_constraints=list(COMPOSITE_CONSTRAINTS),
        indexes=list(SECONDARY_INDEXES),
        fulltext=list(FULLTEXT_INDEXES),
    )


def validation_config() -> ValidationConfig:
    return ValidationConfig(
        id_pattern=ID_PATTERN,
        known_labels=set(KNOWN_LABELS),
        known_rel_types=set(KNOWN_REL_TYPES),
        required_rel_types=set(REQUIRED_REL_TYPES),
        orphan_tolerant_labels=set(ORPHAN_TOLERANT_LABELS),
        int_fields=set(INT_FIELDS),
        float_fields=set(FLOAT_FIELDS),
        bool_fields=set(BOOL_FIELDS),
        provenance_exempt_rels={'HAS_ISSUE', 'AFFECTS', 'HAS_RECOMMENDATION',
                                'HAS_METRIC', 'UNRESOLVED'},
        extra_rules=list(ORACLE_RULES),
    )


def _is_entry_point(node: GraphNode) -> bool:
    """What the outside world can call.

    A published spec unit is reachable from outside the package; a private body
    unit is not. Triggers fire without a caller, so they are entry points too.
    """
    if node.label == 'DbTrigger':
        return True
    if node.label != 'DbProgramUnit':
        return False
    return bool(node.properties.get('isStandalone')
                or node.properties.get('isPublished'))


def impact_config() -> ImpactConfig:
    return ImpactConfig(
        weights=dict(REL_IMPACT_WEIGHTS),
        default_weight=0.5,
        excluded_rels=set(IMPACT_EXCLUDED_RELS),
        label_multipliers=dict(MULTIPLIERS),
        entry_predicate=_is_entry_point,
        entry_bonus=6.0,
        test_buckets=[
            ('Program units to re-test',
             lambda row: row['label'] == 'DbProgramUnit'),
            ('Triggers to re-test', lambda row: row['label'] == 'DbTrigger'),
            ('Queries to re-check', lambda row: row['label'] == 'SqlStatement'),
            ('Database objects in scope',
             lambda row: row['label'] in ('DbTable', 'DbView',
                                          'DbMaterializedView', 'DbPackage')),
        ],
    )
