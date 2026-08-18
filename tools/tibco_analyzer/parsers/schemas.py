"""XSD / AESchema parsers: schemas, elements, complex types."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Set

from ..constants import NS
from ..model import GraphNode
from ..utils import safe_parse_xml, safe_text, xsd_type_to_java

logger = logging.getLogger('tibco_analyzer')


class SchemaParserMixin:
    """Parses `*.xsd` and `*.aeschema` files."""

    # =================================================================
    # 2. XSD Schema Parser
    # =================================================================
    def _parse_xsds(self) -> int:
        count = 0
        for xf in sorted(self.tibco_root.rglob('*.xsd')):
            root = safe_parse_xml(xf)
            if root is None:
                continue

            module = self._module_of(xf)
            mod_id = self._ensure_module(module)
            schema_name = xf.stem
            namespace = root.get('targetNamespace', '')

            # Elements
            elements = root.findall('.//xsd:element', NS) + root.findall('.//xs:element', NS)
            # Deduplicate by name
            seen_elems: Set[str] = set()
            unique_elements = []
            for el in elements:
                ename = el.get('name', '')
                if ename and ename not in seen_elems:
                    seen_elems.add(ename)
                    unique_elements.append(el)

            # Complex types
            complex_types = root.findall('.//xsd:complexType', NS) + root.findall('.//xs:complexType', NS)
            named_complex = [ct for ct in complex_types if ct.get('name')]

            # Simple types
            simple_types = root.findall('.//xsd:simpleType', NS) + root.findall('.//xs:simpleType', NS)
            named_simple = [st for st in simple_types if st.get('name')]

            # Schema imports (XSD -> XSD dependencies)
            imports = root.findall('.//xsd:import', NS) + root.findall('.//xs:import', NS)
            includes = root.findall('.//xsd:include', NS) + root.findall('.//xs:include', NS)
            import_locs: Set[str] = set()
            for imp in imports:
                sl = imp.get('schemaLocation', '')
                if sl:
                    import_locs.add(sl)
            for inc in includes:
                sl = inc.get('schemaLocation', '')
                if sl:
                    import_locs.add(sl)

            # Root element detection
            root_elements = []
            for el in root:
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'element':
                    root_elements.append(el.get('name', ''))

            xsd_id = self._next_id('xsd')
            folder = str(xf.parent.relative_to(self.tibco_root))
            rel_path = str(xf.relative_to(self.tibco_root)).replace('\\', '/')

            self._add_node(GraphNode(xsd_id, 'XSD', schema_name, {
                'folder': folder,
                'module': module,
                'namespace': namespace,
                'elementCount': len(unique_elements),
                'complexTypeCount': len(named_complex),
                'simpleTypeCount': len(named_simple),
                'importCount': len(import_locs),
                'rootElements': ', '.join(root_elements[:5]),
                'filePath': rel_path,
            }))

            self._xsd_by_name[schema_name] = xsd_id
            self._xsd_by_path[rel_path] = xsd_id
            # Index by partial path fragments for flexible matching
            for part_idx in range(len(Path(rel_path).parts)):
                partial = '/'.join(Path(rel_path).parts[part_idx:])
                self._xsd_by_path[partial] = xsd_id

            # BELONGS_TO module
            self._add_rel(xsd_id, mod_id, 'BELONGS_TO', purpose='module-membership')

            # -- Create Element nodes --
            for el in unique_elements:
                ename = el.get('name', '')
                etype = el.get('type', '')
                min_occ = el.get('minOccurs', '1')
                max_occ = el.get('maxOccurs', '1')

                elem_id = self._next_id('elem')
                self._add_node(GraphNode(elem_id, 'Element', ename, {
                    'xsdType': etype,
                    'javaType': xsd_type_to_java(etype),
                    'required': min_occ != '0',
                    'multiple': max_occ == 'unbounded' or (max_occ.isdigit() and int(max_occ) > 1),
                    'schemaRef': xsd_id,
                    'module': module,
                }))
                self._add_rel(xsd_id, elem_id, 'CONTAINS', purpose='element-definition')

            # -- ComplexType nodes --
            for ct in named_complex:
                ct_name = ct.get('name', '')
                ct_id = self._next_id('ctype')
                ct_fields = ct.findall('.//xsd:element', NS) + ct.findall('.//xs:element', NS)
                self._add_node(GraphNode(ct_id, 'ComplexType', ct_name, {
                    'fieldCount': len(ct_fields),
                    'schemaRef': xsd_id,
                    'module': module,
                    'javaClass': ct_name,
                }))
                self._add_rel(xsd_id, ct_id, 'CONTAINS', purpose='type-definition')

            # -- Schema import references (deferred) --
            # Sorted: these populate `_xsd_by_location`, whose insertion
            # order decides the order IMPORTS_SCHEMA edges are emitted in.
            for loc in sorted(import_locs):
                loc_clean = loc.lstrip('/')
                self._xsd_by_location[f"{xsd_id}->{loc_clean}"] = Path(loc).stem

            count += 1

        self.stats['xsds'] = count
        logger.info(f"  Parsed {count} XSD files")
        return count
    def _parse_aeschemas(self) -> int:
        count = 0
        for af in sorted(self.tibco_root.rglob('*.aeschema')):
            root = safe_parse_xml(af)
            if root is None:
                continue

            module = self._module_of(af)
            mod_id = self._ensure_module(module)
            schema_name = af.stem

            ae_id = self._next_id('aes')
            self._add_node(GraphNode(ae_id, 'AESchema', schema_name, {
                'folder': str(af.parent.relative_to(self.tibco_root)),
                'module': module,
                'filePath': str(af.relative_to(self.tibco_root)),
                'description': 'TIBCO Adapter Enterprise schema',
            }))
            self._add_rel(ae_id, mod_id, 'BELONGS_TO', purpose='module-membership')
            count += 1

        self.stats['aeschemas'] = count
        if count:
            logger.info(f"  Parsed {count} AE schema files")
        return count

    # =================================================================
    # 7. XSLT Transformation Parser
    # =================================================================
