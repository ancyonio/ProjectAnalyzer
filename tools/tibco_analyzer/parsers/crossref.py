"""Cross-reference resolution.

Second pass over the parsed artefacts, resolving deferred references into
real edges: CALLS, USES_XSD, USES_WSDL, IMPORTS_SCHEMA, REFERENCES,
DEPENDS_ON. Unresolved sub-process targets become explicit
`ExternalReference` nodes instead of self-loops, so the graph never lies
about what could not be resolved.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Set, Tuple

from ..model import GraphNode
from ..utils import safe_text

logger = logging.getLogger('tibco_analyzer')


def _target_stem(target: str) -> str:
    """Bare process name from a sub-process call target.

    Handles both conventions: BW5 writes a path like `Folder/Name.process`,
    BW6 writes either a `.bwp` path or a dotted qualified name such as
    `Processes.SubFlow`.
    """
    stem = target.replace('\\', '/').split('/')[-1]
    for ext in ('.process', '.bwp'):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break
    return stem.split('.')[-1] if '.' in stem else stem


class CrossReferenceMixin:
    """Resolves deferred references into graph relationships."""

    def _build_cross_references(self) -> int:
        """Resolve deferred relationships: CALLS, USES_XSD, REFERENCES,
        IMPORTS_SCHEMA, DEPENDS_ON."""
        rel_count = 0

        # -- 8a. CALLS (subprocess invocations) --
        for nid, node in list(self.nodes.items()):
            if node.label != 'Activity':
                continue
            target = node.properties.get('callsProcess', '')
            if not target:
                continue

            target_clean = _target_stem(target)
            resolved = (
                self._process_by_path.get(target.lstrip('/')) or
                self._process_by_name.get(target_clean) or
                self._process_by_path.get(target)
            )
            if resolved:
                self._add_rel(nid, resolved, 'CALLS', purpose='subprocess-invocation',
                              targetPath=target)
                rel_count += 1
            else:
                # Unresolved target: materialise it as an explicit node so the
                # gap is visible in the graph instead of hidden in a self-loop.
                ext_id = self._ensure_external_reference(target_clean, target)
                self._add_rel(nid, ext_id, 'CALLS_EXTERNAL',
                              purpose='unresolved-subprocess', targetPath=target)
                rel_count += 1

        # -- 8b. USES_XSD (process -> XSD via stored schema refs) --
        # `sorted` throughout this pass: the deferred refs are sets, and set
        # iteration order varies with the interpreter's hash seed. Without it
        # two runs over unchanged source emit the same edges in a different
        # order, which breaks diffing graph.json between runs.
        for proc_id, schema_refs in self._process_schema_refs.items():
            for ref in sorted(schema_refs):
                ref_clean = ref.lstrip('/')
                ref_stem = Path(ref).stem

                # Try to match the XSD by path fragment
                xsd_id = None
                for path_key, xid in self._xsd_by_path.items():
                    if ref_clean == path_key or path_key.endswith(ref_clean) or ref_clean.endswith(path_key):
                        xsd_id = xid
                        break
                if not xsd_id:
                    xsd_id = self._xsd_by_name.get(ref_stem)

                if xsd_id:
                    self._add_rel(proc_id, xsd_id, 'USES_XSD',
                                  schemaLocation=ref_clean,
                                  purpose='schema-dependency')
                    rel_count += 1

        # -- 8c. USES_WSDL (process -> WSDL via stored wsdl refs) --
        for proc_id, wsdl_refs in self._process_wsdl_refs.items():
            for ref in sorted(wsdl_refs):
                ref_clean = ref.lstrip('/')
                ref_stem = Path(ref).stem

                wsdl_id = None
                for path_key, wid in self._wsdl_by_location.items():
                    if '->' not in path_key and (ref_clean == path_key or path_key.endswith(ref_clean)):
                        wsdl_id = wid
                        break
                if not wsdl_id:
                    wsdl_id = self._wsdl_by_name.get(ref_stem)

                if wsdl_id:
                    self._add_rel(proc_id, wsdl_id, 'USES_WSDL',
                                  wsdlLocation=ref_clean,
                                  purpose='wsdl-dependency')
                    rel_count += 1

        # -- 8d. IMPORTS_SCHEMA (XSD -> XSD) --
        for ref_key, ref_stem in list(self._xsd_by_location.items()):
            if '->' not in ref_key:
                continue
            parts = ref_key.split('->', 1)
            source_xsd_id = parts[0]
            target_loc = parts[1]

            target_xsd_id = None
            for path_key, xid in self._xsd_by_path.items():
                if target_loc in path_key or path_key.endswith(target_loc):
                    target_xsd_id = xid
                    break
            if not target_xsd_id:
                target_xsd_id = self._xsd_by_name.get(ref_stem)

            if target_xsd_id and source_xsd_id in self.nodes:
                self._add_rel(source_xsd_id, target_xsd_id, 'IMPORTS_SCHEMA',
                              schemaLocation=target_loc,
                              purpose='schema-import')
                rel_count += 1

        # -- 8e. WSDL -> XSD imports --
        for ref_key, ref_stem in list(self._wsdl_by_location.items()):
            if '->' not in ref_key:
                continue
            parts = ref_key.split('->', 1)
            wsdl_id = parts[0]
            xsd_loc = parts[1]

            xsd_id = None
            for path_key, xid in self._xsd_by_path.items():
                if xsd_loc in path_key or path_key.endswith(xsd_loc):
                    xsd_id = xid
                    break
            if not xsd_id:
                xsd_id = self._xsd_by_name.get(ref_stem)

            if xsd_id and wsdl_id in self.nodes:
                self._add_rel(wsdl_id, xsd_id, 'IMPORTS_SCHEMA',
                              purpose='wsdl-schema-dependency')
                rel_count += 1

        # -- 8f. REFERENCES (process -> shared resource via stored refs) --
        for proc_id, resource_refs in self._process_resource_refs.items():
            for sr in sorted(resource_refs):
                sr_clean = sr.lstrip('/')
                # Try to match by various path patterns
                res_id = None
                for res_path, rid in self._resource_by_path.items():
                    if rid and (sr_clean == res_path or sr_clean.endswith(res_path) or res_path.endswith(sr_clean)):
                        res_id = rid
                        break
                if res_id:
                    self._add_rel(proc_id, res_id, 'REFERENCES',
                                  purpose='shared-resource-usage',
                                  resourcePath=sr_clean)
                    rel_count += 1

        # -- 8g. DEPENDS_ON (module -> module via cross-module subprocess calls) --
        module_deps: Set[Tuple[str, str]] = set()
        for nid, node in self.nodes.items():
            if node.label == 'Activity' and node.properties.get('callsProcess'):
                caller_proc = node.properties.get('processRef', '')
                caller_mod = self.nodes.get(caller_proc, GraphNode('', '', '', {})).properties.get('module', '')
                target = node.properties.get('callsProcess', '')
                target_clean = _target_stem(target)
                target_proc = self._process_by_name.get(target_clean)
                if target_proc:
                    target_mod = self.nodes[target_proc].properties.get('module', '')
                    if caller_mod and target_mod and caller_mod != target_mod:
                        dep_key = (caller_mod, target_mod)
                        if dep_key not in module_deps:
                            module_deps.add(dep_key)
                            caller_mod_id = self._module_ids.get(caller_mod)
                            target_mod_id = self._module_ids.get(target_mod)
                            if caller_mod_id and target_mod_id:
                                self._add_rel(caller_mod_id, target_mod_id, 'DEPENDS_ON',
                                              purpose='cross-module-dependency')
                                rel_count += 1

        # -- 8h. CONFIGURED_BY (process -> global variable via %%GV%% references) --
        rel_count += self._link_global_variables()

        # -- 8i. EXPOSES (service -> process serving the same namespace) --
        rel_count += self._link_services_to_processes()

        self.stats['cross_references'] = rel_count
        logger.info(f"  Built {rel_count} cross-reference relationships")
        return rel_count

    # ------------------------------------------------------------------
    def _link_global_variables(self) -> int:
        """Wire processes to the global variables they interpolate.

        BW substitutes `%%VarName%%` at runtime, so a textual scan of the
        process XML is the authoritative way to find configuration usage.
        Answers "which services break if this property changes?".
        """
        import re

        gvar_by_name: Dict[str, List[str]] = {}
        for nid, node in self.nodes.items():
            if node.label == 'GlobalVariable':
                gvar_by_name.setdefault(node.name, []).append(nid)
                short = node.name.rsplit('/', 1)[-1]
                if short != node.name:
                    gvar_by_name.setdefault(short, []).append(nid)
        if not gvar_by_name:
            return 0

        pattern = re.compile(r'%%([A-Za-z0-9_./\-]+)%%')
        count = 0
        seen: Set[Tuple[str, str]] = set()
        for nid, node in list(self.nodes.items()):
            if node.label != 'BWProcess' or not node.properties.get('filePath'):
                continue
            path = self.tibco_root / str(node.properties['filePath'])
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            for match in sorted(set(pattern.findall(text))):
                for candidate in (match, match.rsplit('/', 1)[-1]):
                    for gid in gvar_by_name.get(candidate, []):
                        key = (nid, gid)
                        if key in seen:
                            continue
                        seen.add(key)
                        self._add_rel(nid, gid, 'CONFIGURED_BY',
                                      purpose='global-variable-usage',
                                      reference=f'%%{match}%%')
                        count += 1
        return count

    def _link_services_to_processes(self) -> int:
        """Link a WSDL service to the process that implements it.

        Evidence used, in order: the process referenced the WSDL location
        (USES_WSDL), or the process and the service share a target namespace.
        """
        count = 0
        proc_by_ns: Dict[str, List[str]] = {}
        for nid, node in self.nodes.items():
            if node.label == 'BWProcess':
                ns = str(node.properties.get('targetNamespace', ''))
                if ns:
                    proc_by_ns.setdefault(ns, []).append(nid)

        seen: Set[Tuple[str, str]] = set()
        for rel in list(self.rels):
            if rel.rel_type != 'USES_WSDL':
                continue
            key = (rel.end_id, rel.start_id)
            if key in seen:
                continue
            seen.add(key)
            self._add_rel(rel.end_id, rel.start_id, 'EXPOSES',
                          purpose='service-implementation', evidence='wsdl-reference')
            count += 1

        for nid, node in self.nodes.items():
            if node.label != 'Service':
                continue
            ns = str(node.properties.get('namespace', ''))
            for proc_id in proc_by_ns.get(ns, []):
                key = (nid, proc_id)
                if key in seen:
                    continue
                seen.add(key)
                self._add_rel(nid, proc_id, 'EXPOSES',
                              purpose='service-implementation',
                              evidence='shared-target-namespace')
                count += 1
        return count

    # =================================================================
    # 9. Output Writers
    # =================================================================
