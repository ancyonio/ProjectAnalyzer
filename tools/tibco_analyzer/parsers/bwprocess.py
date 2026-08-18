"""BW6 / BusinessWorks Container Edition `.bwp` process parser.

A `.bwp` file is a **BPEL 2.0 process** carrying TIBCO extensions, which makes
it structurally unrelated to BW5's `.process` format:

| Concern | BW5 `.process` | BW6 `.bwp` |
|---------|----------------|------------|
| Root | `pd:ProcessDefinition` | `bpws:process` / `sca-bpel:process` |
| Activity | `pd:activity` + `pd:type` (Java class) | `bpws:extensionActivity` -> `bwext:BWActivity/@activityTypeID` |
| Entry point | `pd:starter` | `bpws:receive[@createInstance='yes']` or an HTTP/JMS receive activity |
| Control flow | `pd:transition` (from/to) | `bpws:link` (source/target) plus `bpws:sequence` order |
| Error handling | `pd:errorSchemas` / error transitions | `bpws:faultHandlers` -> `catch` / `catchAll` |
| Schema refs | `xsd:import` | `bpws:import[@importType='…XMLSchema']` |

Everything is normalised onto the *same* node labels, categories and
relationship types the BW5 parser emits, so downstream analysis — entry-point
detection, complexity, blast radius, diagrams, reports — treats a BW6 estate
identically to a BW5 one.

Coverage note: BPEL is a large language. This parser models the constructs
that carry migration signal (activities, links, sequence order, fault
handlers, scopes, imports, sub-process calls). Correlation sets, event
handlers and compensation handlers are not modelled; activities inside them
are still discovered by the recursive walk.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..constants import (
    BPEL_ACTIVITY_MAP,
    BPEL_STRUCTURED,
    ENTRY_POINT_CATEGORIES,
    NS6,
    bw6_activity_mapping,
)
from ..model import GraphNode
from ..utils import activity_details, localname, safe_parse_xml, safe_text

logger = logging.getLogger('tibco_analyzer')

# Structured constructs worth recording as Group nodes. `sequence` is omitted:
# almost every process has one and it carries no migration signal.
_GROUP_CONSTRUCTS = BPEL_STRUCTURED - {'sequence', 'else', 'elseif'}

# Local tag/attribute names that name a called sub-process.
_CALLED_PROCESS_KEYS = ('processname', 'subprocessname', 'calledprocess',
                        'processpath')


class BwpProcessParserMixin:
    """Parses `*.bwp` (BW6 / BWCE) BPEL process definitions."""

    # ------------------------------------------------------------------
    def _parse_bwp_processes(self) -> int:
        count = 0
        for pf in sorted(self.tibco_root.rglob('*.bwp')):
            root = safe_parse_xml(pf)
            if root is None:
                continue
            if localname(root.tag) != 'process':
                logger.debug("  %s: root is %s, not a BPEL process - skipped",
                             pf.name, localname(root.tag))
                continue
            self._parse_one_bwp(pf, root)
            count += 1
            if count % 25 == 0:
                logger.info("  Parsed %s .bwp files...", count)

        self.stats['bwp_processes'] = count
        if count:
            logger.info("  Parsed %s BW6/BWCE .bwp process files", count)
        return count

    # ------------------------------------------------------------------
    def _parse_one_bwp(self, pf: Path, root) -> None:
        module = self._module_of(pf)
        mod_id = self._ensure_module(module)

        raw_name = root.get('name', pf.stem)
        proc_name = raw_name.replace('\\', '/').split('/')[-1].split('.')[-1] or pf.stem
        target_ns = root.get('targetNamespace', '')

        # -- imports: schema and WSDL references --
        schema_refs: Set[str] = set()
        wsdl_refs: Set[str] = set()
        for imp in root.iter():
            if localname(imp.tag) != 'import':
                continue
            loc = imp.get('location') or imp.get('schemaLocation') or ''
            if not loc:
                continue
            itype = imp.get('importType', '')
            if 'wsdl' in itype.lower() or loc.lower().endswith('.wsdl'):
                wsdl_refs.add(loc)
            else:
                schema_refs.add(loc)

        # -- walk the activity tree --
        walker = _BpelWalker(root)
        walker.walk()

        activity_count = len(walker.activities)
        group_count = len(walker.groups)
        fault_handlers = walker.fault_handlers

        # Entry point: an explicit receive-style activity wins; otherwise a
        # BPEL receive that creates the instance means the process is an
        # externally invocable service operation.
        entry_type = 'NONE'
        entry_endpoint = ''
        for act in walker.activities:
            if act['category'] in ENTRY_POINT_CATEGORIES:
                entry_type = act['category']
                entry_endpoint = act['details'].get('endpointUri', '')
                break
        else:
            if walker.creates_instance:
                entry_type = 'SERVICE_OPERATION'
                entry_endpoint = walker.first_operation

        # -- complexity, scored on the same scale as BW5 --
        transition_count = len(walker.links) + len(walker.sequence_edges)
        complexity_score = (activity_count
                            + (transition_count * 0.5)
                            + (len(fault_handlers) * 3)
                            + (group_count * 2)
                            + (len(schema_refs) * 0.5))
        tier = ('Critical' if complexity_score > 30 else
                'High' if complexity_score > 15 else
                'Medium' if complexity_score > 5 else 'Low')

        proc_id = self._next_id('bwp')
        folder = str(pf.parent.relative_to(self.tibco_root))
        rel_path = str(pf.relative_to(self.tibco_root)).replace('\\', '/')
        self._add_node(GraphNode(proc_id, 'BWProcess', proc_name, {
            'folder': folder,
            'module': module,
            'bwVersion': 'BW6',
            'processType': 'BPEL',
            'qualifiedName': raw_name,
            'callable': walker.callable_flag,
            'entryType': entry_type,
            'endpoint': entry_endpoint,
            'activityCount': activity_count,
            'transitionCount': transition_count,
            'errorHandlerCount': len(fault_handlers),
            'groupCount': group_count,
            'schemaRefCount': len(schema_refs),
            'wsdlRefCount': len(wsdl_refs),
            'processVarCount': walker.variable_count,
            'complexityScore': round(complexity_score, 1),
            'tier': tier,
            'targetNamespace': target_ns,
            'filePath': rel_path,
        }))

        # Index under every form a caller might reference.
        self._process_by_name[proc_name] = proc_id
        self._process_by_name.setdefault(raw_name, proc_id)
        self._process_by_path[raw_name] = proc_id
        self._process_by_path[rel_path] = proc_id

        self._add_rel(proc_id, mod_id, 'BELONGS_TO', purpose='module-membership')
        self._process_schema_refs[proc_id] = schema_refs
        self._process_wsdl_refs[proc_id] = wsdl_refs

        # -- shared-resource bindings (BW6 property -> resource name) --
        # A `.bwp` never names a resource file. It declares a process property
        # carrying `sca-bpel:sharedResourceType` whose literal value is the
        # resource's fully-qualified name, and activities reference that
        # property by name. Resolve the binding here so both the process and
        # the individual activities get credited with the resource they use.
        resource_bindings = _shared_resource_bindings(root)

        # -- activities --
        shared_resource_refs: Set[str] = set(resource_bindings.values())
        for idx, act in enumerate(walker.activities, 1):
            props: Dict[str, Any] = {
                'rawType': act['raw_type'],
                'resourceType': act['bpel_construct'],
                'category': act['category'],
                'springEquivalent': act['spring'],
                'order': idx,
                'processRef': proc_id,
                'module': module,
                'bwVersion': 'BW6',
            }
            props.update(act['details'])
            if act['is_entry']:
                props['isStarter'] = True
                props['entryType'] = entry_type
            if act['operation']:
                props['operation'] = act['operation']
            if act['partner_link']:
                props['partnerLink'] = act['partner_link']

            self.activity_type_counts[act['category']] += 1
            act_id = self._next_id('act')
            self._add_node(GraphNode(act_id, 'Activity', act['name'], props))
            self._activity_key_to_id[f"{proc_id}:{act['name']}"] = act_id
            act['node_id'] = act_id

            self._add_rel(proc_id, act_id, 'EXECUTES', order=idx,
                          purpose='activity-execution')

            if act['calls_process']:
                self._add_node_prop(act_id, 'callsProcess', act['calls_process'])
            act_resource_refs = set(act['resource_refs'])
            # An activity points at a resource by naming the bound property.
            for prop_name, resource_name in resource_bindings.items():
                if prop_name in act['property_refs']:
                    act_resource_refs.add(resource_name)
            if act_resource_refs:
                self._add_node_prop(act_id, 'sharedResources',
                                    ', '.join(sorted(act_resource_refs)))
            shared_resource_refs.update(act_resource_refs)

        self._process_resource_refs[proc_id] = shared_resource_refs

        # -- control flow: explicit links first, then sequence order --
        by_name = {a['name']: a.get('node_id') for a in walker.activities}
        for link in walker.links:
            src = by_name.get(link['from'])
            dst = by_name.get(link['to'])
            if src and dst and src != dst:
                self._add_rel(src, dst, 'TRANSITIONS_TO',
                              conditionType='link' if not link['condition'] else 'xpath',
                              condition=link['condition'][:200],
                              linkName=link['name'],
                              purpose='control-flow')

        for src_name, dst_name in walker.sequence_edges:
            src = by_name.get(src_name)
            dst = by_name.get(dst_name)
            if src and dst and src != dst:
                self._add_rel(src, dst, 'TRANSITIONS_TO',
                              conditionType='always',
                              purpose='sequence-flow')

        # -- groups (scopes, flows, loops, branches) --
        for grp in walker.groups:
            grp_id = self._next_id('grp')
            self._add_node(GraphNode(grp_id, 'Group', grp['name'], {
                'groupType': grp['construct'],
                'processRef': proc_id,
                'module': module,
                'bwVersion': 'BW6',
            }))
            self._add_rel(proc_id, grp_id, 'HAS_GROUP', purpose='process-grouping')

        # -- fault handlers --
        for fh in fault_handlers:
            err_id = self._next_id('err')
            self._add_node(GraphNode(err_id, 'ErrorHandler', fh['name'], {
                'faultName': fh['fault_name'],
                'type': fh['type'],
                'scope': fh['scope'],
                'processRef': proc_id,
                'module': module,
                'bwVersion': 'BW6',
            }))
            self._add_rel(proc_id, err_id, 'HANDLES_ERROR',
                          faultName=fh['fault_name'], purpose='fault-handling')

        self.migration_complexity[proc_name] = {
            'tier': tier,
            'score': round(complexity_score, 1),
            'activities': activity_count,
            'transitions': transition_count,
            'errors': len(fault_handlers),
            'groups': group_count,
            'subprocess_calls': sum(1 for a in walker.activities if a['calls_process']),
            'shared_resources': len(shared_resource_refs),
            'schema_refs': len(schema_refs),
            'wsdl_refs': len(wsdl_refs),
            'bwVersion': 'BW6',
        }


# ──────────────────────────────────────────────────────────────
# BPEL tree walker
# ──────────────────────────────────────────────────────────────
class _BpelWalker:
    """Collects activities, links, groups and fault handlers from a BPEL tree.

    Kept separate from the mixin so the traversal is testable on its own and
    the mixin stays a thin adapter onto the graph.
    """

    def __init__(self, root):
        self.root = root
        self.activities: List[Dict[str, Any]] = []
        self.groups: List[Dict[str, str]] = []
        self.fault_handlers: List[Dict[str, str]] = []
        self.links: List[Dict[str, str]] = []
        self.sequence_edges: List[Tuple[str, str]] = []
        self.creates_instance = False
        self.first_operation = ''
        self.variable_count = 0
        self.callable_flag = ''
        self._names: Set[str] = set()
        self._link_sources: Dict[str, str] = {}
        self._link_targets: Dict[str, str] = {}
        self._link_conditions: Dict[str, str] = {}

    # ------------------------------------------------------------------
    def walk(self) -> None:
        for el in self.root:
            tag = localname(el.tag)
            if tag == 'variables':
                self.variable_count = sum(1 for v in el if localname(v.tag) == 'variable')
            elif tag == 'ProcessInfo':
                self.callable_flag = el.get('callable', '')
            elif tag == 'faultHandlers':
                self._collect_fault_handlers(el, scope='process')
            else:
                self._visit(el, scope='process')

        # ProcessInfo can sit anywhere; catch it if it was nested.
        if not self.callable_flag:
            info = self.root.find('.//{%s}ProcessInfo' % NS6['tibex'])
            if info is not None:
                self.callable_flag = info.get('callable', '')

        self._resolve_links()

    # ------------------------------------------------------------------
    def _visit(self, el, scope: str) -> None:
        tag = localname(el.tag)

        if tag == 'faultHandlers':
            self._collect_fault_handlers(el, scope)
            return
        if tag == 'links':
            for link in el:
                if localname(link.tag) == 'link':
                    self._link_conditions.setdefault(link.get('name', ''), '')
            self._descend(el, scope)
            return

        if tag == 'extensionActivity':
            self._add_extension_activity(el)
            return

        if tag in BPEL_ACTIVITY_MAP:
            self._add_bpel_activity(el, tag)
            self._descend(el, scope)
            return

        if tag in BPEL_STRUCTURED:
            name = el.get('name', '')
            if tag in _GROUP_CONSTRUCTS and name:
                self.groups.append({'name': name, 'construct': tag})
            if tag == 'sequence':
                self._link_sequence(el)
            self._descend(el, tag if tag == 'scope' else scope)
            return

        self._descend(el, scope)

    def _descend(self, el, scope: str) -> None:
        for child in el:
            self._visit(child, scope)

    # ------------------------------------------------------------------
    def _unique_name(self, proposed: str, fallback: str) -> str:
        name = proposed or fallback
        if name not in self._names:
            self._names.add(name)
            return name
        n = 2
        while f'{name}_{n}' in self._names:
            n += 1
        unique = f'{name}_{n}'
        self._names.add(unique)
        return unique

    def _record_links(self, el, name: str) -> None:
        """Attach this activity to any BPEL links it sources or targets."""
        for child in el:
            ctag = localname(child.tag)
            if ctag == 'sources':
                for s in child:
                    if localname(s.tag) != 'source':
                        continue
                    lname = s.get('linkName', '')
                    if lname:
                        self._link_sources[lname] = name
                        cond = ''
                        for c in s:
                            if localname(c.tag) == 'transitionCondition':
                                cond = (c.text or '').strip()
                        if cond:
                            self._link_conditions[lname] = cond
            elif ctag == 'targets':
                for tgt in child:
                    if localname(tgt.tag) == 'target':
                        lname = tgt.get('linkName', '')
                        if lname:
                            self._link_targets[lname] = name

    def _resolve_links(self) -> None:
        for lname in sorted(set(self._link_sources) | set(self._link_targets)):
            src = self._link_sources.get(lname)
            dst = self._link_targets.get(lname)
            if src and dst:
                self.links.append({'name': lname, 'from': src, 'to': dst,
                                   'condition': self._link_conditions.get(lname, '')})

    def _link_sequence(self, seq_el) -> None:
        """Consecutive activity children of a sequence run in order."""
        ordered = [localname(c.tag) for c in seq_el]
        names: List[str] = []
        for child, tag in zip(seq_el, ordered):
            if tag == 'extensionActivity':
                names.append(_ext_activity_name(child))
            elif tag in BPEL_ACTIVITY_MAP:
                names.append(child.get('name', ''))
        names = [n for n in names if n]
        for a, b in zip(names, names[1:]):
            self.sequence_edges.append((a, b))

    # ------------------------------------------------------------------
    def _add_extension_activity(self, el) -> None:
        inner = None
        for child in el:
            if localname(child.tag) in EXT_ACTIVITY_TAGS:
                inner = child
                break
        target = inner if inner is not None else el
        raw_name = _ext_activity_name(el)

        type_id = ''
        for node in target.iter():
            if localname(node.tag) == 'BWActivity':
                type_id = node.get('activityTypeID', '') or node.get('type', '')
                break
        if not type_id:
            for node in target.iter():
                tid = node.get('activityTypeID')
                if tid:
                    type_id = tid
                    break

        mapping = bw6_activity_mapping(type_id)
        category = mapping['category']
        spring = mapping['spring']

        calls_process = _called_process(target)
        if category == 'CUSTOM' and calls_process:
            # Some BW6 call-process activities carry no activityTypeID. The
            # call target is evidence enough: an activity that names a process
            # it invokes is a subprocess call, not unclassified custom work.
            category = 'CALL_PROCESS'
            spring = '@Autowired + service.method()'

        details = activity_details(target)
        name = self._unique_name(raw_name, f'Activity_{len(self.activities) + 1}')

        self.activities.append({
            'name': name,
            'raw_type': type_id,
            'bpel_construct': 'extensionActivity',
            'category': category,
            'spring': spring,
            'details': details,
            'is_entry': category in ENTRY_POINT_CATEGORIES,
            'calls_process': calls_process,
            'resource_refs': _resource_refs(target),
            'property_refs': _property_refs(target),
            'operation': target.get('operation', ''),
            'partner_link': target.get('partnerLink', ''),
        })
        self._record_links(target, name)
        if target is not el:
            self._record_links(el, name)

    def _add_bpel_activity(self, el, tag: str) -> None:
        mapping = BPEL_ACTIVITY_MAP[tag]
        name = self._unique_name(el.get('name', ''),
                                 f'{tag}_{len(self.activities) + 1}')
        operation = el.get('operation', '')

        is_entry = False
        if tag == 'receive' and el.get('createInstance', '').lower() == 'yes':
            self.creates_instance = True
            is_entry = True
            if not self.first_operation:
                self.first_operation = operation

        self.activities.append({
            'name': name,
            'raw_type': f'bpel:{tag}',
            'bpel_construct': tag,
            'category': mapping['category'],
            'spring': mapping['spring'],
            'details': activity_details(el),
            'is_entry': is_entry,
            'calls_process': _called_process(el),
            'resource_refs': _resource_refs(el),
            'property_refs': _property_refs(el),
            'operation': operation,
            'partner_link': el.get('partnerLink', ''),
        })
        self._record_links(el, name)

    # ------------------------------------------------------------------
    def _collect_fault_handlers(self, el, scope: str) -> None:
        for child in el:
            tag = localname(child.tag)
            if tag not in ('catch', 'catchAll'):
                continue
            fault = child.get('faultName', '') if tag == 'catch' else 'ALL'
            short = fault.split(':')[-1] or 'ALL'
            self.fault_handlers.append({
                'name': f'FaultHandler_{short}',
                'fault_name': fault,
                'type': 'CATCH_ALL' if tag == 'catchAll' else 'CATCH',
                'scope': scope,
            })
            # Activities inside a handler are real work; keep walking.
            self._descend(child, scope)


# ──────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────
# The three shapes a BW6 extension activity takes. `receiveEvent` is the
# event-source form -- the one that makes a process an entry point -- and
# omitting it left every message-driven starter unnamed.
EXT_ACTIVITY_TAGS = ('extActivity', 'activityExtension', 'receiveEvent')


def _ext_activity_name(el) -> str:
    """Name of an extensionActivity: on the wrapper or on its inner element."""
    if el.get('name'):
        return el.get('name', '')
    for child in el:
        if localname(child.tag) in EXT_ACTIVITY_TAGS:
            return child.get('name', '')
    return ''


def _called_process(el) -> str:
    """Target of a call-process activity, from a tag or an attribute."""
    for node in el.iter():
        if localname(node.tag).lower() in _CALLED_PROCESS_KEYS:
            value = (node.text or '').strip()
            if value:
                return value
        for attr, value in node.attrib.items():
            if localname(attr).lower() in _CALLED_PROCESS_KEYS and value.strip():
                return value.strip()
    return ''


def _resource_refs(el) -> Set[str]:
    """Direct shared-resource references, BW5 style.

    BW5 names the resource file inline (`/SharedResources/JDBC.sharedjdbc`).
    BW6 does not -- it goes through a process property, which
    `_shared_resource_bindings` resolves instead.
    """
    refs: Set[str] = set()
    for node in el.iter():
        candidates = [(node.text or '').strip()] + [v.strip() for v in node.attrib.values()]
        for value in candidates:
            if not value or len(value) > 300:
                continue
            lowered = value.lower()
            if lowered.startswith(('shared', '/shared')) or '.shared' in lowered \
                    or lowered.endswith(('.httpproxy', '.id', '.rvtransport')):
                refs.add(value)
    return refs


def _property_refs(el) -> Set[str]:
    """Bare identifiers an activity uses, any of which may name a property.

    BW6 activities reference a shared resource through attributes such as
    `connectionReference="jmsConnection"` or `httpClientSR="httpClientResource"`.
    The attribute name varies by activity type, so every short identifier-shaped
    attribute value is collected and matched against the declared bindings.
    """
    refs: Set[str] = set()
    for node in el.iter():
        for value in node.attrib.values():
            value = value.strip()
            if value and len(value) <= 128 and value.replace('_', '').isalnum():
                refs.add(value)
    return refs


def _shared_resource_bindings(root) -> Dict[str, str]:
    """Map a BW6 process property name to the resource it is bound to.

    Looks for variables carrying `sca-bpel:sharedResourceType` and reads the
    `bpws:literal` holding the resource's fully-qualified name, e.g.
    `jmsConnection -> Assignment_5.JMSConnectionResource`.
    """
    bindings: Dict[str, str] = {}
    if root is None:
        return bindings
    for el in root.iter():
        if not any(key.split('}')[-1] == 'sharedResourceType' for key in el.attrib):
            continue
        prop_name = (el.get('name') or '').strip()
        if not prop_name:
            continue
        for child in el.iter():
            if child.tag.split('}')[-1] == 'literal':
                literal = (child.text or '').strip()
                if literal:
                    bindings[prop_name] = literal
                break
    return bindings
