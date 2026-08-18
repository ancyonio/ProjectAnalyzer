"""Physical and logical schema wiring.

The one place that turns the constants catalogue into the objects the core
engines need, so the Neo4j export, the CI gate and the blast radius can never
disagree about the federated vocabulary.
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
from .validate_rules import ESTATE_RULES


def neo4j_schema() -> Neo4jSchema:
    return Neo4jSchema(
        title='Federated Estate Knowledge Graph',
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
                                'HAS_METRIC', 'UNRESOLVED', 'CONTAINS_ESTATE'},
        extra_rules=list(ESTATE_RULES),
    )


def _is_entry_point(node: GraphNode) -> bool:
    """What the outside world can reach, in whichever estate it lives.

    Each dialect has its own answer, and a federated blast radius has to
    honour all three: an APEX page, a TIBCO process starter or exposed
    service, and a published Oracle spec unit or trigger are all places a
    change becomes visible to somebody outside the code.
    """
    label = node.label
    if label == 'ApexPage':
        return True
    if label == 'BWProcess':
        return bool(node.properties.get('isEntryPoint')
                    or node.properties.get('entryType') not in (None, '', 'NONE'))
    if label == 'Activity':
        return bool(node.properties.get('isStarter'))
    if label in ('Service', 'Operation'):
        return True
    if label == 'DbTrigger':
        return True
    if label == 'DbProgramUnit':
        return bool(node.properties.get('isStandalone')
                    or node.properties.get('isPublished'))
    return False


def impact_config() -> ImpactConfig:
    return ImpactConfig(
        weights=dict(REL_IMPACT_WEIGHTS),
        default_weight=0.5,
        excluded_rels=set(IMPACT_EXCLUDED_RELS),
        label_multipliers=dict(MULTIPLIERS),
        entry_predicate=_is_entry_point,
        entry_bonus=6.0,
        test_buckets=[
            ('TIBCO processes to re-test',
             lambda row: row['label'] == 'BWProcess'),
            ('APEX pages to re-test', lambda row: row['label'] == 'ApexPage'),
            ('Oracle program units to re-test',
             lambda row: row['label'] in ('DbProgramUnit', 'DbTrigger')),
            ('Database objects in scope',
             lambda row: row['label'] in ('DbTable', 'DbView',
                                          'DbMaterializedView', 'DbPackage')),
            ('Integration points to re-test',
             lambda row: row['label'] in ('SharedResource', 'Adapter',
                                          'Service', 'Operation')),
        ],
    )
