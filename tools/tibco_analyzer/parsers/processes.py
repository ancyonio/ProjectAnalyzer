"""BW `.process` file parser.

Extracts processes, activities, transitions, groups, error handlers,
sub-process calls and shared-resource references. Ported from the original
single-file analyzer; behaviour preserved, wiring modularised.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple

from ..constants import ACTIVITY_SPRING_MAP, NS
from ..model import GraphNode
from ..utils import activity_details, safe_parse_xml, safe_text

logger = logging.getLogger('tibco_analyzer')


def _config_of(element):
    """The `<config>` block of an activity or starter.

    `find(...) or find(...)` is wrong on ElementTree: an Element with no
    children is falsy, so an empty match silently falls through to the next
    branch. Test against None explicitly.
    """
    cfg = element.find('config')
    if cfg is None:
        cfg = element.find('.//config')
    return cfg


class ProcessParserMixin:
    """Parses `*.process` (BW5) definitions."""

    def _parse_processes(self) -> int:
        """Parse all .process files extracting activities, transitions,
        groups, errors, subprocess calls, and resource refs."""
        count = 0
        for pf in sorted(self.tibco_root.rglob('*.process')):
            root = safe_parse_xml(pf)
            if root is None:
                continue

            module = self._module_of(pf)
            mod_id = self._ensure_module(module)

            # Process name
            pname_el = root.find('.//pd:name', NS)
            raw_name = safe_text(pname_el, pf.stem)
            proc_name = raw_name.split('/')[-1].replace('.process', '') if '/' in raw_name else raw_name.replace('.process', '')

            # Starter info. The starter IS an executable step -- it is the
            # entry point activity itself -- so it is treated as an activity
            # below rather than being read for metadata and discarded. Without
            # that, every transition leaving the starter fails to resolve and
            # the control flow graph is disconnected at its head.
            starter = root.find('.//pd:starter', NS)
            entry_type = 'NONE'
            entry_endpoint = ''
            entry_shared_channel = ''
            if starter is not None:
                stype = safe_text(starter.find('pd:type', NS))
                mapping = ACTIVITY_SPRING_MAP.get(stype, {})
                entry_type = mapping.get('category', 'UNKNOWN')
                cfg = _config_of(starter)
                if cfg is not None:
                    sc = cfg.find('sharedChannel')
                    if sc is not None and sc.text:
                        entry_shared_channel = sc.text.strip()
                    detail = activity_details(cfg)
                    entry_endpoint = (detail.get('endpointUri', '')
                                      or detail.get('httpMethod', ''))

            # Executable steps = the starter, when present, plus every activity.
            activities = ([] if starter is None else [starter]) \
                + root.findall('.//pd:activity', NS)
            activity_count = len(activities)

            # Transitions
            transitions = root.findall('.//pd:transition', NS)
            transition_count = len(transitions)

            # Error schemas
            error_schemas = root.findall('.//pd:errorSchemas', NS)
            error_handler_count = 0
            for es in error_schemas:
                error_handler_count += len(list(es))

            # Groups
            groups = root.findall('.//pd:group', NS)
            group_count = len(groups)

            # XSD imports (schema references)
            xsd_imports = root.findall('.//xsd:import', NS)
            schema_refs: Set[str] = set()
            for imp in xsd_imports:
                sl = imp.get('schemaLocation', '')
                if sl:
                    schema_refs.add(sl)

            # WSDL imports
            wsdl_imports = root.findall('.//wsdl:import', NS)
            wsdl_refs: Set[str] = set()
            for imp in wsdl_imports:
                loc = imp.get('location', '')
                if loc:
                    wsdl_refs.add(loc)

            # Target namespace
            target_ns = ''
            tns_el = root.find('.//pd:targetNamespace', NS)
            if tns_el is not None:
                target_ns = safe_text(tns_el)
            elif root.get('targetNamespace'):
                target_ns = root.get('targetNamespace', '')

            # Complexity scoring
            complexity_score = activity_count + (transition_count * 0.5) + (error_handler_count * 3) + (group_count * 2) + (len(schema_refs) * 0.5)
            tier = 'Critical' if complexity_score > 30 else 'High' if complexity_score > 15 else 'Medium' if complexity_score > 5 else 'Low'

            # Process variables
            pvars = root.findall('.//pd:processVariables', NS)
            proc_var_count = sum(len(list(pv)) for pv in pvars)

            # Create BWProcess node
            proc_id = self._next_id('bwp')
            folder = str(pf.parent.relative_to(self.tibco_root))
            self._add_node(GraphNode(proc_id, 'BWProcess', proc_name, {
                'folder': folder,
                'module': module,
                'bwVersion': 'BW5',
                'processType': 'BW5_PROCESS',
                'entryType': entry_type,
                'endpoint': entry_endpoint,
                'activityCount': activity_count,
                'transitionCount': transition_count,
                'errorHandlerCount': error_handler_count,
                'groupCount': group_count,
                'schemaRefCount': len(schema_refs),
                'wsdlRefCount': len(wsdl_refs),
                'processVarCount': proc_var_count,
                'complexityScore': round(complexity_score, 1),
                'tier': tier,
                'targetNamespace': target_ns,
                'filePath': str(pf.relative_to(self.tibco_root)),
            }))

            self._process_by_name[proc_name] = proc_id
            self._process_by_path[raw_name] = proc_id
            self._process_by_path[str(pf.relative_to(self.tibco_root))] = proc_id

            # BELONGS_TO module
            self._add_rel(proc_id, mod_id, 'BELONGS_TO', purpose='module-membership')

            # -- Store deferred schema/wsdl/resource refs --
            self._process_schema_refs[proc_id] = schema_refs
            self._process_wsdl_refs[proc_id] = wsdl_refs

            # -- Parse Activities --
            subprocess_calls: List[Tuple[str, str]] = []
            shared_resource_refs: Set[str] = set()

            for idx, act in enumerate(activities, 1):
                is_starter = starter is not None and act is starter
                default_name = 'Starter' if is_starter else f'Activity_{idx}'
                act_name = act.get('name', default_name)
                atype = safe_text(act.find('pd:type', NS))
                res_type = safe_text(act.find('pd:resourceType', NS))

                mapping = ACTIVITY_SPRING_MAP.get(atype, {})
                spring_eq = mapping.get('spring', 'Manual Implementation')
                category = mapping.get('category', 'CUSTOM')

                self.activity_type_counts[category] += 1

                props = {
                    'rawType': atype,
                    'resourceType': res_type,
                    'category': category,
                    'springEquivalent': spring_eq,
                    'order': idx,
                    'processRef': proc_id,
                    'module': module,
                    'bwVersion': 'BW5',
                }
                if is_starter:
                    props['isStarter'] = True
                    props['entryType'] = entry_type

                # Inspect config for sub-process calls, shared resources and
                # the behavioural payload (SQL, destinations, URIs, files).
                cfg = _config_of(act)
                if cfg is not None:
                    props.update(activity_details(cfg))

                act_id = self._next_id('act')
                self._add_node(GraphNode(act_id, 'Activity', act_name, props))
                self._activity_key_to_id[f"{proc_id}:{act_name}"] = act_id

                # EXECUTES
                self._add_rel(proc_id, act_id, 'EXECUTES', order=idx, purpose='activity-execution')

                if cfg is not None:
                    # Subprocess call
                    pname_ref = cfg.find('processName')
                    if pname_ref is not None and pname_ref.text:
                        subprocess_calls.append((act_name, pname_ref.text.strip()))

                    # Shared channel / connection refs
                    for tag in ('sharedChannel', 'sharedConfiguration', 'JMSConnection',
                                'jmsConnection', 'proxyConnection', 'basicHttpAuthIdentity',
                                'sharedResourceProperty', 'JDBCSharedConfig', 'jdbcSharedConfig'):
                        ref_el = cfg.find(tag)
                        if ref_el is not None and ref_el.text:
                            shared_resource_refs.add(ref_el.text.strip())

            if entry_shared_channel:
                shared_resource_refs.add(entry_shared_channel)

            # Store shared resource refs for deferred linking
            self._process_resource_refs[proc_id] = shared_resource_refs

            # -- Parse Transitions --
            resolved_transitions = 0
            for tr in transitions:
                from_el = tr.find('pd:from', NS)
                to_el = tr.find('pd:to', NS)
                ctype_el = tr.find('pd:conditionType', NS)
                xpath_el = tr.find('pd:xpath', NS)
                desc_el = tr.find('pd:xpathDescription', NS)

                fr = safe_text(from_el)
                to = safe_text(to_el)
                ctype = safe_text(ctype_el, 'always')
                xpath_cond = safe_text(xpath_el)
                xpath_desc = safe_text(desc_el)

                from_id = self._activity_key_to_id.get(f"{proc_id}:{fr}")
                to_id = self._activity_key_to_id.get(f"{proc_id}:{to}")

                if from_id and to_id:
                    resolved_transitions += 1
                    self._add_rel(from_id, to_id, 'TRANSITIONS_TO',
                                  conditionType=ctype,
                                  condition=xpath_cond[:200] if xpath_cond else '',
                                  description=xpath_desc,
                                  purpose='control-flow')
                else:
                    logger.debug("  %s: unresolved transition %r -> %r",
                                 pf.name, fr, to)

                # Build error handler node for error transitions
                if ctype == 'error':
                    err_id = self._next_id('err')
                    self._add_node(GraphNode(err_id, 'ErrorHandler', f"ErrorHandler_{fr}", {
                        'sourceActivity': fr,
                        'handlerActivity': to,
                        'type': 'ERROR_TRANSITION',
                        'processRef': proc_id,
                        'module': module,
                    }))
                    self._add_rel(proc_id, err_id, 'HANDLES_ERROR',
                                  sourceActivity=fr, purpose='fault-handling')

            # -- Parse Groups --
            for grp in groups:
                grp_name = grp.get('name', 'UnnamedGroup')
                grp_type_el = grp.find('pd:type', NS)
                grp_type = safe_text(grp_type_el)
                grp_id = self._next_id('grp')
                self._add_node(GraphNode(grp_id, 'Group', grp_name, {
                    'groupType': grp_type,
                    'processRef': proc_id,
                    'module': module,
                }))
                self._add_rel(proc_id, grp_id, 'HAS_GROUP', purpose='process-grouping')

                # Group-level transitions
                grp_transitions = grp.findall('.//pd:transition', NS)
                for gt in grp_transitions:
                    gfrom = safe_text(gt.find('pd:from', NS))
                    gto = safe_text(gt.find('pd:to', NS))
                    gfrom_id = self._activity_key_to_id.get(f"{proc_id}:{gfrom}")
                    gto_id = self._activity_key_to_id.get(f"{proc_id}:{gto}")
                    if gfrom_id and gto_id:
                        gctype = safe_text(gt.find('pd:conditionType', NS), 'always')
                        gxpath = safe_text(gt.find('pd:xpath', NS))
                        self._add_rel(gfrom_id, gto_id, 'TRANSITIONS_TO',
                                      conditionType=gctype,
                                      condition=gxpath[:200] if gxpath else '',
                                      purpose='group-flow')

            # -- Subprocess CALLS (store target path on activity for deferred resolution) --
            for act_name, target_path in subprocess_calls:
                caller_act_id = self._activity_key_to_id.get(f"{proc_id}:{act_name}")
                if caller_act_id:
                    self._add_node_prop(caller_act_id, 'callsProcess', target_path)

            # `transitionCount` is what the XML declares; `resolvedTransitions`
            # is how many became edges. A gap means a transition referenced a
            # step this parser did not model -- visible, not silent.
            self._add_node_prop(proc_id, 'resolvedTransitions', resolved_transitions)
            if resolved_transitions != transition_count:
                self._add_node_prop(proc_id, 'unresolvedTransitions',
                                    transition_count - resolved_transitions)

            self.migration_complexity[proc_name] = {
                'tier': tier,
                'score': round(complexity_score, 1),
                'activities': activity_count,
                'transitions': transition_count,
                'errors': error_handler_count,
                'groups': group_count,
                'subprocess_calls': len(subprocess_calls),
                'shared_resources': len(shared_resource_refs),
                'schema_refs': len(schema_refs),
                'wsdl_refs': len(wsdl_refs),
            }

            count += 1
            if count % 25 == 0:
                logger.info(f"  Parsed {count} process files...")

        self.stats['processes'] = count
        logger.info(f"  Parsed {count} process files ({sum(self.activity_type_counts.values())} activities)")
        return count
