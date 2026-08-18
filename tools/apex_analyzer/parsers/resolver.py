"""Name resolution — spec §10.2.

Turns a name a parser found in SQL into a real database object, and records
*how* it was resolved. Every data-access edge therefore carries a
`resolution` and a `confidence`, so an agent can tell an asserted dependency
from an educated guess, and the validator can report coverage.

    1 OWNER.OBJECT exists                 exact            1.00
    2 unqualified, in the parsing schema  schema_default   0.95
    3 matches a synonym                   synonym          0.90
    4 unique across the other schemas     heuristic        0.70
    5 assembled at runtime                dynamic          0.40
    6 no match                            unresolved       0.00

A miss is never dropped: it becomes a `:DbObject:Unresolved` node so that
"page 12 references a table that does not exist" is a finding rather than
silence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from analyzer_core.ids import column_id, db_ident, object_id, unresolved_id

from ..constants import RESOLUTION_CONFIDENCE


@dataclass
class Resolution:
    node_id: str
    owner: str
    name: str
    label: str
    resolution: str
    confidence: float
    resolved: bool

    @property
    def is_unresolved(self) -> bool:
        return not self.resolved


class Resolver:
    """Index of the database extract, plus the resolution ladder over it."""

    def __init__(self, parsing_schema: str = ''):
        self.parsing_schema = db_ident(parsing_schema)
        # (owner, name) -> label
        self.objects: Dict[Tuple[str, str], str] = {}
        # name -> [(owner, label), …]
        self.by_name: Dict[str, List[Tuple[str, str]]] = {}
        # (owner, table) -> {column}
        self.columns: Dict[Tuple[str, str], Set[str]] = {}
        # (owner, synonym) -> (target owner, target name)
        self.synonyms: Dict[Tuple[str, str], Tuple[str, str]] = {}
        # (owner, package) -> {unit name}
        self.units: Dict[Tuple[str, str], Set[str]] = {}
        self.standalone_units: Dict[Tuple[str, str], str] = {}
        self.unresolved: Dict[str, Dict[str, str]] = {}
        self.counters: Dict[str, int] = {}

    # ------------------------------------------------------------------
    def register_object(self, owner: str, name: str, label: str) -> None:
        owner, name = db_ident(owner), db_ident(name)
        if not name:
            return
        key = (owner, name)
        # a table beats a synonym of the same name when both are extracted
        if key not in self.objects or label in ('DbTable', 'DbView'):
            self.objects[key] = label
        self.by_name.setdefault(name, [])
        if (owner, label) not in self.by_name[name]:
            self.by_name[name].append((owner, label))

    def register_column(self, owner: str, table: str, column: str) -> None:
        self.columns.setdefault((db_ident(owner), db_ident(table)), set()).add(db_ident(column))

    def register_synonym(self, owner: str, name: str,
                         target_owner: str, target_name: str) -> None:
        self.synonyms[(db_ident(owner), db_ident(name))] = (db_ident(target_owner),
                                                            db_ident(target_name))

    def register_unit(self, owner: str, package: Optional[str], name: str) -> None:
        owner, name = db_ident(owner), db_ident(name)
        if package:
            self.units.setdefault((owner, db_ident(package)), set()).add(name)
        else:
            self.standalone_units[(owner, name)] = name

    @property
    def has_dictionary(self) -> bool:
        return bool(self.objects)

    # ------------------------------------------------------------------
    def resolve_object(self, owner: str, name: str,
                       expected: Optional[Set[str]] = None,
                       record: bool = True) -> Resolution:
        """Resolve a table/view/package-shaped name.

        `record=False` is used for internal probes (does this package exist?)
        so that a probe miss never distorts the coverage metric.
        """
        owner, name = db_ident(owner), db_ident(name)
        if not name:
            return self._unresolved(name, 'empty name')

        if not self.has_dictionary:
            # No dictionary extract: keep the reference, state the uncertainty.
            return Resolution(object_id(owner or self.parsing_schema or 'UNKNOWN', name),
                              owner or self.parsing_schema, name, 'DbTable',
                              'heuristic', RESOLUTION_CONFIDENCE['heuristic'], True)

        if owner and (owner, name) in self.objects:
            return self._hit(owner, name, 'exact')

        if not owner and self.parsing_schema:
            if (self.parsing_schema, name) in self.objects:
                return self._hit(self.parsing_schema, name, 'schema_default')

        for synonym_owner in (owner, self.parsing_schema, 'PUBLIC'):
            key = (db_ident(synonym_owner), name)
            if key in self.synonyms:
                target_owner, target_name = self.synonyms[key]
                if (target_owner, target_name) in self.objects:
                    return self._hit(target_owner, target_name, 'synonym')

        if not owner:
            matches = self.by_name.get(name, [])
            if len(matches) == 1:
                return self._hit(matches[0][0], name, 'heuristic')

        return self._unresolved(f'{owner}.{name}' if owner else name,
                                'not present in the database extract', record)

    def resolve_unit(self, package: str, name: str) -> Resolution:
        """Resolve a `PACKAGE.PROCEDURE` (or standalone procedure) call."""
        package, name = db_ident(package), db_ident(name)
        if not self.has_dictionary:
            return Resolution(f'db:{package}.{name}' if package else f'db:{name}',
                              '', name, 'DbProgramUnit', 'heuristic',
                              RESOLUTION_CONFIDENCE['heuristic'], True)

        # package.procedure, in the parsing schema or any extracted schema
        for owner in self._candidate_owners():
            if package and (owner, package) in self.units and name in self.units[(owner, package)]:
                resolution = 'exact' if owner == self.parsing_schema else 'heuristic'
                return Resolution(f'db:{owner}.{package}.{name}', owner, name,
                                  'DbProgramUnit', resolution,
                                  RESOLUTION_CONFIDENCE[resolution], True)
        # owner.procedure (standalone unit qualified by schema)
        if package and (package, name) in self.standalone_units:
            return Resolution(f'db:{package}.{name}', package, name, 'DbProgramUnit',
                              'exact', RESOLUTION_CONFIDENCE['exact'], True)
        # package resolved through a synonym
        synonym = self.synonyms.get((self.parsing_schema, package)) or \
            self.synonyms.get(('PUBLIC', package))
        if synonym and (synonym[0], synonym[1]) in self.objects:
            target_owner, target_package = synonym
            if name in self.units.get((target_owner, target_package), set()):
                return Resolution(f'db:{target_owner}.{target_package}.{name}',
                                  target_owner, name, 'DbProgramUnit', 'synonym',
                                  RESOLUTION_CONFIDENCE['synonym'], True)
        # the package exists but the unit is not in the extract (body not read)
        if package:
            package_hit = self.resolve_object('', package, {'DbPackage'}, record=False)
            if package_hit.resolved and package_hit.label == 'DbPackage':
                return Resolution(f'db:{package_hit.owner}.{package}.{name}',
                                  package_hit.owner, name, 'DbProgramUnit',
                                  'heuristic', RESOLUTION_CONFIDENCE['heuristic'], True)
        return self._unresolved(f'{package}.{name}' if package else name,
                                'no matching program unit in the database extract')

    def resolve_column(self, owner: str, table: str, column: str) -> Optional[str]:
        """Return the column node id, or None when the column does not exist.

        This is the filter that makes liberal column extraction safe.
        """
        owner, table, column = db_ident(owner), db_ident(table), db_ident(column)
        if not self.columns:
            return None
        if column in self.columns.get((owner, table), set()):
            return column_id(owner, table, column)
        return None

    def columns_of(self, owner: str, table: str) -> Set[str]:
        return self.columns.get((db_ident(owner), db_ident(table)), set())

    # ------------------------------------------------------------------
    def _candidate_owners(self) -> List[str]:
        owners = [self.parsing_schema] if self.parsing_schema else []
        owners += sorted({owner for owner, _ in self.objects} - set(owners))
        return owners

    def _hit(self, owner: str, name: str, resolution: str) -> Resolution:
        label = self.objects.get((db_ident(owner), db_ident(name)), 'DbTable')
        self.counters[resolution] = self.counters.get(resolution, 0) + 1
        return Resolution(object_id(owner, name), db_ident(owner), db_ident(name),
                          label, resolution, RESOLUTION_CONFIDENCE[resolution], True)

    def _unresolved(self, raw: str, reason: str, record: bool = True) -> Resolution:
        raw = db_ident(raw)
        if record:
            self.counters['unresolved'] = self.counters.get('unresolved', 0) + 1
            self.unresolved[raw] = {'rawName': raw, 'reason': reason}
        return Resolution(unresolved_id(raw), '', raw, 'DbObject', 'unresolved',
                          RESOLUTION_CONFIDENCE['unresolved'], False)

    # ------------------------------------------------------------------
    def coverage(self) -> Dict[str, object]:
        total = sum(self.counters.values())
        strong = sum(self.counters.get(k, 0)
                     for k in ('exact', 'schema_default', 'synonym'))
        return {
            'resolutions': dict(sorted(self.counters.items(), key=lambda kv: -kv[1])),
            'totalResolutions': total,
            'strongResolutions': strong,
            'resolutionCoverage': round(strong / total, 4) if total else 1.0,
            'unresolvedNames': sorted(self.unresolved),
        }
