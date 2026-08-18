"""Physical and logical schema wiring.

The one place that turns the constants catalogue into the objects the core
engines need. Nothing else in the package constructs these, so the export and
the CI gate can never disagree about the vocabulary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from analyzer_core.graph.exporters import Neo4jSchema
from analyzer_core.graph.validate import ValidationConfig

from ..constants import (BOOL_FIELDS, COMPOSITE_CONSTRAINTS, FLOAT_FIELDS,
                         FULLTEXT_INDEXES, ID_PATTERN, INT_FIELDS,
                         KNOWN_LABELS, KNOWN_REL_TYPES, ORPHAN_TOLERANT_LABELS,
                         REQUIRED_REL_TYPES, SECONDARY_INDEXES)
from .validate_rules import TIBCO_RULES, csv_roundtrip


def neo4j_schema() -> Neo4jSchema:
    return Neo4jSchema(
        title='TIBCO BusinessWorks Knowledge Graph',
        int_fields=set(INT_FIELDS),
        float_fields=set(FLOAT_FIELDS),
        bool_fields=set(BOOL_FIELDS),
        composite_constraints=list(COMPOSITE_CONSTRAINTS),
        indexes=list(SECONDARY_INDEXES),
        fulltext=list(FULLTEXT_INDEXES),
    )


def validation_config(output_dir: Optional[Path] = None) -> ValidationConfig:
    """The gate. Pass `output_dir` to include the CSV round-trip check."""
    return ValidationConfig(
        id_pattern=ID_PATTERN,
        known_labels=set(KNOWN_LABELS),
        known_rel_types=set(KNOWN_REL_TYPES),
        required_rel_types=set(REQUIRED_REL_TYPES),
        orphan_tolerant_labels=set(ORPHAN_TOLERANT_LABELS),
        int_fields=set(INT_FIELDS),
        float_fields=set(FLOAT_FIELDS),
        bool_fields=set(BOOL_FIELDS),
        provenance_exempt_rels={'HAS_ISSUE', 'AFFECTS', 'HAS_RECOMMENDATION'},
        extra_rules=list(TIBCO_RULES) + [csv_roundtrip(output_dir)],
    )
