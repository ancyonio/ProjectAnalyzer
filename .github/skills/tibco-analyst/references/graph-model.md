# Graph model reference

The knowledge graph is the contract between the deterministic layer and the
narrative layer. Everything in it comes from an XML element that exists on disk in
the scanned tree; nothing is inferred.

Persisted as `<output>/graph.json` and exported as `neo4j_nodes.csv` /
`neo4j_relationships.csv` / `neo4j_import.cypher`.

## Node id conventions

Ids are assigned per label in parse order and are stable for a given source tree.
Quote them in every finding.

| Prefix | Label | Prefix | Label |
|--------|-------|--------|-------|
| `mod_` | Module | `svc_` | Service |
| `bwp_` | BWProcess | `op_` | Operation |
| `act_` | Activity | `res_` | SharedResource |
| `grp_` | Group | `adp_` | Adapter |
| `err_` | ErrorHandler | `sys_` | System |
| `xsd_` | XSD | `gvar_` | GlobalVariable |
| `elem_` | Element | `xslt_` | DataTransformation |
| `ctype_` | ComplexType | `aes_` | AESchema |
| | | `ext_` | ExternalReference |

Two properties are near-universal and are what make a node citable:
`module` (owning module folder) and `filePath` (POSIX path relative to the scanned
root). Nodes that exist only inside a parent file — `Activity`, `Element`,
`ComplexType`, `Operation`, `ErrorHandler`, `Group` — carry no `filePath`; cite
the parent's path plus the node id instead.

## Node labels

### Module
A top-level folder in the scanned tree (typically `<Name>.module`). The unit of
ownership and the first candidate boundary for a Spring Boot service.

| Property | Meaning |
|----------|---------|
| `type` | Always `TIBCO_MODULE` |
| `description` | Generated description |

**Spring Boot target:** a deployable service or a Maven module, depending on how
the module dependency graph (`DEPENDS_ON`) looks.

### BWProcess
One `.process` file: the unit of business logic and the unit of migration.

| Property | Meaning |
|----------|---------|
| `entryType` | Entry-point category or `NONE` (see the table below) |
| `endpoint` | HTTP method or endpoint detail when the starter exposes one |
| `activityCount`, `transitionCount`, `errorHandlerCount`, `groupCount` | Structural counts used by the complexity score |
| `schemaRefCount`, `wsdlRefCount`, `processVarCount` | Reference counts |
| `complexityScore`, `tier` | Migration sizing (see below) |
| `targetNamespace` | Namespace, also used to link a Service to its implementing process |
| `folder`, `module`, `filePath` | Location |

**Spring Boot target:** a `@Service` class; an entry-point process additionally
becomes a controller, listener or scheduled component.

Entry-point categories (`entryType`) and their targets:

| `entryType` | Trigger | Spring Boot target |
|-------------|---------|--------------------|
| `HTTP_RECEIVER` | HTTP event source | `@RestController` |
| `SOAP_RECEIVER` | SOAP event source | Spring WS `@Endpoint` |
| `JMS_RECEIVER` | JMS queue consumer | `@JmsListener` |
| `JMS_SUBSCRIBE` | JMS topic consumer | `@JmsListener` (topic) |
| `RV_SUBSCRIBE` | Rendezvous consumer | `@JmsListener` after RV→JMS migration |
| `FILE_POLLER` | File poller | Spring Integration / `WatchService` |
| `TIMER` | Timer | `@Scheduled` |
| `NONE` | Not externally reachable | Internal service method |

### Activity
One `<activity>` inside a process: the atomic unit of work.

| Property | Meaning |
|----------|---------|
| `rawType` | The TIBCO plugin class, e.g. `com.tibco.plugin.jdbc.JDBCQueryActivity` |
| `category` | Normalised category, e.g. `JDBC_QUERY`, `HTTP_REQUEST`, `MAPPER`, `CATCH`; `CUSTOM` when the raw type is unmapped |
| `springEquivalent` | Migration target, e.g. `JdbcTemplate.query()`; `Manual Implementation` when unmapped |
| `order` | Position within the process, used for flow and sequence diagrams |
| `processRef` | Owning `BWProcess` node id |
| `callsProcess` | Present only on sub-process call activities: the raw target path |

**Spring Boot target:** the `springEquivalent` property. A `category` of `CUSTOM`
with `Manual Implementation` is a signal for design attention, not a defect.

### Group
A `<group>` inside a process: loop, transaction or critical section.

| Property | Meaning |
|----------|---------|
| `groupType` | The TIBCO group type |
| `processRef` | Owning process |

**Spring Boot target:** a loop, `@Transactional` boundary or lock, per `groupType`.
Groups are weighted heavily in the complexity score because they usually hide
iteration or transaction semantics.

### XSD
One `.xsd` file: a data contract.

| Property | Meaning |
|----------|---------|
| `namespace` | `targetNamespace` — must be preserved through migration |
| `elementCount`, `complexTypeCount`, `simpleTypeCount`, `importCount` | Structure counts |
| `rootElements` | First five top-level element names |

**Spring Boot target:** JAXB / POJO model classes generated from the same schema.

### Element
A named `<xsd:element>`. Deduplicated by name within a schema.

| Property | Meaning |
|----------|---------|
| `xsdType` | Declared XSD type |
| `javaType` | Mapped Java type (`xs:dateTime` → `java.time.LocalDateTime`, unknown → `Object`) |
| `required` | `minOccurs != "0"` |
| `multiple` | `maxOccurs` unbounded or > 1 |
| `schemaRef` | Owning `XSD` node id |

**Spring Boot target:** a field on the generated model class. Elements are the unit
of field-level impact analysis.

### ComplexType
A named `<xsd:complexType>`.

| Property | Meaning |
|----------|---------|
| `fieldCount` | Number of nested element declarations |
| `javaClass` | Proposed Java class name (the type name) |
| `schemaRef` | Owning schema |

### Service
One `.wsdl` file: a service contract.

| Property | Meaning |
|----------|---------|
| `namespace` | `targetNamespace` |
| `operationCount`, `bindingStyle`, `endpointUrl` | Contract detail |
| `type` | `WSDL` |
| `springEquivalent` | `Spring WS @Endpoint` for document binding, otherwise `@RestController` |

### Operation
One WSDL `portType` operation.

| Property | Meaning |
|----------|---------|
| `inputMessage`, `outputMessage` | Message QNames |
| `serviceRef` | Owning service |
| `springEquivalent` | `@PayloadRoot handler` |

### Adapter
A synthetic node created for major connection resources (HTTP, JMS, JDBC, RV). It
exists to separate "the configuration file" from "the thing it talks to".

| Property | Meaning |
|----------|---------|
| `type` | Resource type, e.g. `JDBC_CONNECTION` |
| `technology` | `HTTP`, `JMS`, `JDBC`, `RV` |
| `resourceRef` | The `SharedResource` it configures |

### System
A synthetic external system, one per technology, named `<TECH>_System`.

| Property | Meaning |
|----------|---------|
| `technology` | `HTTP`, `JMS`, `JDBC`, `RV`, … |
| `type` | `EXTERNAL_SYSTEM` |

`System` nodes are grouping abstractions, not named third parties. Do not present
`JDBC_System` as "the customer database" unless a `SharedResource` property
(`host`, `url`, `driver`) says so.

### GlobalVariable
One `<globalVariable>` from a `.substvar` file: the configuration surface.

| Property | Meaning |
|----------|---------|
| `value` | Default value; masked to `***MASKED***` when the name contains password, secret, credential or key |
| `varType` | Declared type |
| `deployable`, `serviceSettable` | Whether it can be overridden at deployment / service level |
| `springEquivalent` | `application.yml property` |

### ErrorHandler
Materialised from an error transition. One node per error transition found.

| Property | Meaning |
|----------|---------|
| `sourceActivity` | The activity whose failure is handled |
| `handlerActivity` | The activity that handles it |
| `type` | `ERROR_TRANSITION` |
| `processRef` | Owning process |

**Spring Boot target:** `@ExceptionHandler` or a try/catch around the equivalent call.

### SharedResource
One shared-resource file (`.sharedhttp`, `.sharedjdbc`, `.sharedjmscon`,
`.sharedvariable`, `.httpProxy`, `.rvtransport`, `.id`, …).

| Property | Meaning |
|----------|---------|
| `resourceType` | e.g. `JDBC_CONNECTION`, `HTTP_CONNECTION`, `IDENTITY` |
| `technology` | `JDBC`, `HTTP`, `JMS`, `RV`, `Auth`, … |
| `springEquivalent` | e.g. `DataSource / JdbcTemplate` |
| `host`, `port`, `url`, `driver` | Connection detail when present in the file |

### DataTransformation
One `.xsl` / `.xslt` file.

| Property | Meaning |
|----------|---------|
| `type` | `XSLT` |
| `springEquivalent` | `javax.xml.transform / MapStruct` |

Transformations are parsed as an inventory only: the analyzer does not resolve
which activity invokes which stylesheet, so an unreferenced transformation is a
weaker dead-code signal than an orphan schema.

### AESchema
One `.aeschema` file (TIBCO Adapter Enterprise schema). Inventory only, with
`folder`, `module` and `filePath`.

### ExternalReference
A referenced artefact that is **not** present in the scanned tree. Created when a
sub-process call target cannot be resolved.

| Property | Meaning |
|----------|---------|
| `type` | `UNRESOLVED_PROCESS` |
| `targetPath` | The raw reference as written in the calling process |
| `note` | "Referenced by a process but not found in the scanned source tree" |

Reached by `CALLS_EXTERNAL` from the calling activity. This is the graph's way of
being honest about scope gaps: rather than a self-loop or a silent drop, the
unresolved reference becomes visible, is counted by `validate` under the
`unresolved-references` rule, and is tolerated in the orphan check.

Treat every `ExternalReference` as a scope question for the migration: either the
artefact lives in another repository, or the caller is dead. Say which you do not
know rather than guessing.

## Relationships

Direction is written as `(start) -[TYPE]-> (end)`. The weight column is the impact
multiplier applied per hop during blast-radius traversal (see
`impact-analysis.md`); a higher weight means a change propagates more strongly
across that edge.

| Type | Direction | Meaning | Weight |
|------|-----------|---------|--------|
| `BELONGS_TO` | BWProcess / XSD / Service / SharedResource / DataTransformation / AESchema → Module | Module membership | 0.1, **never traversed** |
| `EXECUTES` | BWProcess → Activity | The process runs this activity; property `order` | 0.8 |
| `TRANSITIONS_TO` | Activity → Activity | Control flow; properties `conditionType` (`always`, `error`, or an XPath condition type), `condition` (XPath, truncated to 200 chars), `description` | 0.4 |
| `CALLS` | Activity → BWProcess | Resolved sub-process invocation; property `targetPath` | 0.9 |
| `CALLS_EXTERNAL` | Activity → ExternalReference | Unresolved sub-process invocation | 0.5 |
| `USES_XSD` | BWProcess → XSD | Schema dependency; property `schemaLocation` | 1.0 |
| `USES_WSDL` | BWProcess → Service | WSDL dependency; property `wsdlLocation` | 1.0 |
| `CONTAINS` | XSD → Element, XSD → ComplexType | Type definition | 0.9 |
| `HANDLES_ERROR` | BWProcess → ErrorHandler | Fault handling; property `sourceActivity` | 0.5 |
| `HAS_GROUP` | BWProcess → Group | Grouping construct | 0.4 |
| `REFERENCES` | BWProcess → SharedResource | Connection or identity usage; property `resourcePath` | 0.7 |
| `CONFIGURED_BY` | Adapter → SharedResource; BWProcess → GlobalVariable | Adapter configuration; `%%Var%%` interpolation with property `reference` | 0.6 |
| `CONFIGURES` | GlobalVariable → Module | The variable belongs to this module's configuration | 0.6 |
| `CONNECTS_TO` | Adapter → System | Outbound integration; property `technology` | 0.6 |
| `IMPORTS_SCHEMA` | XSD → XSD; Service → XSD | Schema import or include | 1.0 |
| `EXPOSES` | Service → Operation; Service → BWProcess | Contract operation; service implementation with property `evidence` (`wsdl-reference` or `shared-target-namespace`) | 0.8 |
| `DEPENDS_ON` | Module → Module | Cross-module sub-process call exists | 0.7 |

Two edges deserve care when writing findings:

- `EXPOSES` from Service to BWProcess is **inferred evidence**, not a declaration.
  Check the `evidence` property: `wsdl-reference` is strong, `shared-target-namespace`
  is circumstantial and should be described as such.
- `CONFIGURED_BY` from BWProcess to GlobalVariable comes from a textual scan for
  `%%VarName%%` in the process XML, which is how BW substitution actually works. It
  is reliable for direct usage and blind to variables referenced only from
  deployment descriptors.

## Canonical subgraph for one process

This is the shape you should expect around any non-trivial `BWProcess`, and the
shape `context/processes/<Name>.md` serialises:

```
                  (Module)
                     ^
                     | BELONGS_TO
                     |
   CALLS      (BWProcess) --EXECUTES--> (Activity) --TRANSITIONS_TO--> (Activity)
 (Activity) -----^   | | | |                 |
 [caller]            | | | |                 +--CALLS--> (BWProcess) [callee]
                     | | | |                 +--CALLS_EXTERNAL--> (ExternalReference)
                     | | | |
                     | | | +--HAS_GROUP--> (Group)
                     | | +----HANDLES_ERROR--> (ErrorHandler)
                     | +------REFERENCES--> (SharedResource) <--CONFIGURED_BY-- (Adapter)
                     |                                                    |
                     |                                             CONNECTS_TO
                     |                                                    v
                     |                                                (System)
                     +--------USES_XSD--> (XSD) --CONTAINS--> (Element | ComplexType)
                     |                      |
                     |                      +--IMPORTS_SCHEMA--> (XSD)
                     +--------USES_WSDL--> (Service) --EXPOSES--> (Operation)
                     +--------CONFIGURED_BY--> (GlobalVariable) --CONFIGURES--> (Module)
```

Reading it in the two useful directions:

- **Downstream** (outgoing from the process): everything the process needs — its
  activities, schemas, contracts, resources and configuration. This is the scope of
  migrating that process.
- **Upstream** (incoming to the process): its callers and the entry points above
  them. This is the blast radius of changing it.

## Complexity scoring

```
complexityScore = activityCount
                + 0.5 x transitionCount
                + 3   x errorHandlerCount
                + 2   x groupCount
                + 0.5 x schemaRefCount
```

| Tier | Condition |
|------|-----------|
| Critical | score > 30 |
| High | score > 15 |
| Medium | score > 5 |
| Low | otherwise |

The weights encode migration effort, not runtime cost: error handlers and groups
carry the highest per-unit weight because fault semantics and transaction or loop
semantics are what a rewrite most often gets wrong. Report the score as a relative
sizing signal, never as an effort estimate in days.
