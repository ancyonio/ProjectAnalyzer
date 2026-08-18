"""WSDL service contract parser: services, operations, bindings, endpoints."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Set

from ..constants import NS
from ..model import GraphNode
from ..utils import safe_parse_xml, safe_text

logger = logging.getLogger('tibco_analyzer')


class ServiceParserMixin:
    """Parses `*.wsdl` service contracts."""

    # =================================================================
    # 3. WSDL Service Parser
    # =================================================================
    def _parse_wsdls(self) -> int:
        count = 0
        for wf in sorted(self.tibco_root.rglob('*.wsdl')):
            root = safe_parse_xml(wf)
            if root is None:
                continue

            module = self._module_of(wf)
            mod_id = self._ensure_module(module)
            svc_name = wf.stem
            namespace = root.get('targetNamespace', '')
            rel_path = str(wf.relative_to(self.tibco_root)).replace('\\', '/')

            # Extract operations from portType
            operations: List[Dict[str, str]] = []
            port_types = root.findall('.//wsdl:portType', NS)
            if not port_types:
                port_types = [el for el in root.iter() if el.tag.endswith('portType')]
            for pt in port_types:
                for op in pt:
                    tag = op.tag.split('}')[-1] if '}' in op.tag else op.tag
                    if tag == 'operation':
                        op_name = op.get('name', '')
                        inp = op.find('.//wsdl:input', NS)
                        out = op.find('.//wsdl:output', NS)
                        if inp is None:
                            inp = next((c for c in op if c.tag.endswith('input')), None)
                        if out is None:
                            out = next((c for c in op if c.tag.endswith('output')), None)
                        operations.append({
                            'name': op_name,
                            'input': inp.get('message', '') if inp is not None else '',
                            'output': out.get('message', '') if out is not None else '',
                        })

            # Extract bindings
            bindings = root.findall('.//wsdl:binding', NS)
            binding_style = ''
            for b in bindings:
                soap_binding = b.find('.//soap:binding', NS)
                if soap_binding is not None:
                    binding_style = soap_binding.get('style', 'document')

            # Extract service ports / endpoints
            services = root.findall('.//wsdl:service', NS)
            endpoint_url = ''
            for svc in services:
                ports = svc.findall('.//wsdl:port', NS)
                for port in ports:
                    addr = port.find('.//soap:address', NS)
                    if addr is not None:
                        endpoint_url = addr.get('location', '')

            # Extract schema imports from WSDL types section
            types_section = root.find('.//wsdl:types', NS)
            wsdl_schema_refs: Set[str] = set()
            if types_section is not None:
                for imp in types_section.findall('.//xsd:import', NS):
                    sl = imp.get('schemaLocation', '')
                    if sl:
                        wsdl_schema_refs.add(sl.lstrip('/'))

            svc_id = self._next_id('svc')
            self._add_node(GraphNode(svc_id, 'Service', svc_name, {
                'folder': str(wf.parent.relative_to(self.tibco_root)),
                'module': module,
                'namespace': namespace,
                'operationCount': len(operations),
                'bindingStyle': binding_style,
                'endpointUrl': endpoint_url,
                'schemaRefCount': len(wsdl_schema_refs),
                'filePath': rel_path,
                'type': 'WSDL',
                'springEquivalent': 'Spring WS @Endpoint' if binding_style == 'document' else '@RestController',
            }))

            self._wsdl_by_name[svc_name] = svc_id
            for part_idx in range(len(Path(rel_path).parts)):
                partial = '/'.join(Path(rel_path).parts[part_idx:])
                self._wsdl_by_location[partial] = svc_id

            # BELONGS_TO
            self._add_rel(svc_id, mod_id, 'BELONGS_TO', purpose='module-membership')

            # -- Create Operation nodes --
            for op in operations:
                op_id = self._next_id('op')
                self._add_node(GraphNode(op_id, 'Operation', op['name'], {
                    'inputMessage': op['input'],
                    'outputMessage': op['output'],
                    'serviceRef': svc_id,
                    'module': module,
                    'springEquivalent': '@PayloadRoot handler',
                }))
                self._add_rel(svc_id, op_id, 'EXPOSES', purpose='service-operation')

            # -- WSDL -> XSD import references (deferred) --
            # Sorted, for the same reason as the XSD imports above.
            for ref in sorted(wsdl_schema_refs):
                self._wsdl_by_location[f"{svc_id}->{ref}"] = Path(ref).stem

            count += 1

        self.stats['wsdls'] = count
        logger.info(f"  Parsed {count} WSDL files")
        return count

    # =================================================================
    # 4. Shared Resource Parser
    # =================================================================
