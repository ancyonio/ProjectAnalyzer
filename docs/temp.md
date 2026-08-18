For an Oracle project analyzed in Neo4j, I would model it as a Code Knowledge Graph, where Oracle artifacts become nodes and dependencies become relationships.

The key is not to make every line/token a node. Start at the architectural/code-object level and add finer-grained nodes only where they provide analytical value.

1. Recommended Neo4j model
5

A good starting structure is:

Project
  │
  ├── CONTAINS → Schema
  │                │
  │                ├── CONTAINS → Package
  │                │                 ├── HAS_SPEC → PackageSpec
  │                │                 ├── HAS_BODY → PackageBody
  │                │                 └── CONTAINS → Procedure / Function
  │                │
  │                ├── CONTAINS → Procedure
  │                ├── CONTAINS → Function
  │                ├── CONTAINS → Trigger
  │                ├── CONTAINS → View
  │                ├── CONTAINS → Table
  │                └── CONTAINS → Sequence
  │
  └── CONTAINS → SourceFile

Then create dependency relationships between those objects:

Procedure ──CALLS──────────────→ Procedure
Procedure ──CALLS──────────────→ Function
Procedure ──USES───────────────→ Table
Procedure ──READS──────────────→ Table
Procedure ──WRITES─────────────→ Table
Procedure ──USES───────────────→ View
Trigger   ──FIRES_ON───────────→ Table
Function  ──REFERENCES─────────→ Table
View      ──DEPENDS_ON─────────→ Table
Package   ──DEPENDS_ON─────────→ Package
Procedure ──DEFINED_IN─────────→ Package
Object    ──DEFINED_IN─────────→ SourceFile
2. Node types

I would divide nodes into 5 categories.

A. Repository / project nodes
Project
Repository
Branch
Commit
Directory
SourceFile

Example:

(Project)
   OracleDBIQ


(Repository)
   oracle-customer-system


(SourceFile)
   customer_pkg.sql

Relationships:

Project ──HAS_REPOSITORY──> Repository
Repository ──CONTAINS──> SourceFile
SourceFile ──LOCATED_IN──> Directory
B. Oracle database objects

These are your most important nodes.

Schema
Table
Column
View
MaterializedView
Sequence
Synonym
Index
Constraint
Trigger
DatabaseLink
Type

Example:

Schema
  CUSTOMER


Table
  CUSTOMER
  CUSTOMER_ADDRESS
  CUSTOMER_ORDER


Column
  CUSTOMER.CUSTOMER_ID
  CUSTOMER.NAME

Relationships:

Schema ──OWNS──> Table
Table ──HAS_COLUMN──> Column
Table ──HAS_INDEX──> Index
Table ──HAS_CONSTRAINT──> Constraint
Trigger ──FIRES_ON──> Table
View ──DEPENDS_ON──> Table
3. PL/SQL nodes

This is where your graph becomes particularly valuable.

Create nodes for:

Package
PackageSpec
PackageBody
Procedure
Function
Cursor
Exception
RecordType
CollectionType
Variable
Constant

For example:

CUSTOMER_PKG
     │
     ├── PackageSpec
     │
     └── PackageBody
           │
           ├── CREATE_CUSTOMER
           ├── UPDATE_CUSTOMER
           ├── DELETE_CUSTOMER
           └── GET_CUSTOMER

Graph:

Package
  │
  ├──HAS_SPEC──> PackageSpec
  │
  └──HAS_BODY──> PackageBody


PackageBody
  │
  ├──CONTAINS──> Procedure
  └──CONTAINS──> Function
4. Most important relationships

For an Oracle analysis platform, I would define a controlled relationship vocabulary.

Relationship	From	To	Purpose
CONTAINS	Project	File/Object	Hierarchy
OWNS	Schema	Object	Ownership
DEFINED_IN	DB Object	File	Source mapping
CONTAINS	Package	Procedure	Package structure
CALLS	Procedure	Procedure	Call graph
CALLS	Procedure	Function	Call graph
USES	Code Object	DB Object	Generic dependency
READS	Procedure	Table	SELECT dependency
WRITES	Procedure	Table	INSERT/UPDATE/DELETE
REFERENCES	Function	Table	Dependency
DEPENDS_ON	View	Table	View lineage
FIRES_ON	Trigger	Table	Trigger dependency
HAS_COLUMN	Table	Column	Schema structure
JOINS_WITH	Query	Table	SQL relationship
RAISES	Procedure	Exception	Error behavior
USES_CURSOR	Procedure	Cursor	Cursor dependency
USES_TYPE	Procedure	Type	Type dependency
INHERITS	Type	Type	Object type hierarchy
SYNONYM_FOR	Synonym	Object	Indirection
REFERENCES_DBLINK	Object	DatabaseLink	Remote dependency
5. Don't use only USES

One important design decision:

Avoid this:

Procedure ──USES──> Table

for everything.

Instead capture semantic relationships.

For example:

SELECT *
FROM CUSTOMER
WHERE CUSTOMER_ID = p_customer_id;


UPDATE CUSTOMER
SET STATUS = 'A'
WHERE CUSTOMER_ID = p_customer_id;

should become:

GET_CUSTOMER ──READS──> CUSTOMER


UPDATE_CUSTOMER ──WRITES──> CUSTOMER

This enables much more powerful analysis.

For example:

"Which procedures modify CUSTOMER?"

Neo4j can answer directly.

6. SQL Query as a node?

This depends on how deep you want your analysis.

For a basic code graph:

Procedure ──READS──> Table
Procedure ──WRITES──> Table

is sufficient.

For an advanced Oracle Code Intelligence platform, introduce:

SQLStatement

Then:

Procedure
   │
   └──CONTAINS──> SQLStatement
                       │
                       ├──READS──> Table
                       ├──WRITES──> Table
                       └──JOINS──> Table

Example:

Procedure: GET_CUSTOMER_DETAILS


       │
       ▼
SQLStatement
SELECT ...
       │
       ├────────READS──────> CUSTOMER
       │
       └────────READS──────> CUSTOMER_ADDRESS

This is especially useful for your Oracle optimization use case.

7. Add source-code metadata

Every code node should contain properties such as:

id
name
type
schema
file_path
line_start
line_end
source_hash
status
complexity
loc
language
created_date
last_modified

Example:

Procedure
{
   id: "PROC:CUSTOMER:UPDATE_CUSTOMER",
   name: "UPDATE_CUSTOMER",
   schema: "CUSTOMER",
   file_path: "/src/customer/customer_pkg.sql",
   line_start: 120,
   line_end: 185,
   language: "PLSQL",
   complexity: 12,
   loc: 66
}

This becomes extremely useful when an AI agent wants to explain where a problem exists in the repository.

8. Add code quality / analysis nodes

Since you're building an AI-driven Oracle analysis solution, I would go beyond dependencies.

Introduce:

CodeSmell
PerformanceIssue
SecurityIssue
Optimization
Recommendation
TestCase
BusinessRule
Risk
Finding

For example:

Procedure
     │
     ├──HAS_FINDING──> PerformanceIssue
     │                       │
     │                       └──HAS_RECOMMENDATION──> Optimization
     │
     └──HAS_TEST──> TestCase

Example:

UPDATE_CUSTOMER
      │
      └──HAS_FINDING──>
          Full Table Scan
                │
                └──HAS_RECOMMENDATION──>
                    Add index on CUSTOMER_ID
9. Very powerful model: Business + Technical graph

You can eventually connect business concepts to Oracle implementation.

BusinessCapability
       │
       └──IMPLEMENTED_BY──>
BusinessService
       │
       └──IMPLEMENTED_BY──>
Package
       │
       └──CONTAINS──>
Procedure
       │
       └──WRITES──>
Table

For example:

Customer Management
        ↓
Customer Onboarding
        ↓
CUSTOMER_PKG
        ↓
CREATE_CUSTOMER
        ↓
CUSTOMER

This gives you impact analysis from business → code → database.

10. Recommended complete graph

For your Oracle project, I'd use approximately this model:

                         Project
                            │
                      CONTAINS
                            ↓
                       Repository
                            │
                       CONTAINS
                            ↓
                         File
                            │
                       DEFINES
                            ↓
                         Schema
                            │
          ┌─────────────────┼─────────────────┐
          ↓                 ↓                 ↓
       Package           Table            View
          │                 │
      CONTAINS          HAS_COLUMN
          ↓                 ↓
     Procedure          Column
          │
     ┌────┼───────────────┐
     ↓    ↓               ↓
   CALLS READS          WRITES
     ↓    ↓               ↓
 Procedure Table         Table
     │
     │ CONTAINS
     ↓
 SQLStatement
     │
 ┌───┼─────────────┐
 ↓   ↓             ↓
READS WRITES      JOINS
 ↓   ↓             ↓
Table Table       Table

Then add the AI/analysis layer:

Procedure
    │
    ├──HAS_FINDING──> Finding
    │                     │
    │                     └──HAS_RECOMMENDATION──> Recommendation
    │
    ├──HAS_METRIC──> CodeMetric
    │
    └──HAS_TEST──> TestCase
11. Example

Suppose you have:

CREATE OR REPLACE PACKAGE BODY CUSTOMER_PKG AS


  PROCEDURE CREATE_CUSTOMER(
      p_name VARCHAR2
  ) AS
  BEGIN


      INSERT INTO CUSTOMER
      (
          CUSTOMER_ID,
          NAME
      )
      VALUES
      (
          CUSTOMER_SEQ.NEXTVAL,
          p_name
      );


  END;


  PROCEDURE DELETE_CUSTOMER(
      p_customer_id NUMBER
  ) AS
  BEGIN


      DELETE FROM CUSTOMER
      WHERE CUSTOMER_ID = p_customer_id;


  END;


END CUSTOMER_PKG;

Your graph becomes:

CUSTOMER_PKG
      │
      └──CONTAINS──> CREATE_CUSTOMER
      │
      └──CONTAINS──> DELETE_CUSTOMER


CREATE_CUSTOMER
      │
      ├──WRITES──────> CUSTOMER
      │
      └──USES────────> CUSTOMER_SEQ


DELETE_CUSTOMER
      │
      └──WRITES──────> CUSTOMER


CUSTOMER
      │
      └──HAS_COLUMN──> CUSTOMER_ID


CUSTOMER_SEQ
      │
      └──BELONGS_TO──> CUSTOMER_SCHEMA

Now you can ask Neo4j:

Which procedures modify CUSTOMER?

MATCH (p:Procedure)-[:WRITES]->(t:Table)
WHERE t.name = 'CUSTOMER'
RETURN p.name;

Result:

CREATE_CUSTOMER
DELETE_CUSTOMER
12. Impact analysis

This is where Neo4j becomes much more powerful than a simple dependency table.

Suppose:

CUSTOMER
   ↑
   │ WRITES
UPDATE_CUSTOMER
   ↑
   │ CALLS
UPDATE_CUSTOMER_API
   ↑
   │ IMPLEMENTS
CustomerService

If someone changes CUSTOMER, you can traverse backwards:

MATCH path =
  (t:Table {name:'CUSTOMER'})
  <-[:READS|WRITES|USES*1..5]-
  (obj)
RETURN path;

You can answer:

What code will potentially be impacted if CUSTOMER changes?

13. Call graph

Create a dedicated call graph:

API Procedure
      │
     CALLS
      ↓
Service Procedure
      │
     CALLS
      ↓
Utility Function
      │
     READS
      ↓
Table

Query:

MATCH path =
  (p:Procedure {name:'CREATE_ORDER'})
  -[:CALLS*1..10]->
  (target)
RETURN path;

This gives you the complete execution/dependency chain.

14. Add Git information

Because your Oracle project is likely Git-based, I'd also capture:

Repository
Branch
Commit
Developer
Change
PullRequest

Then:

Commit
  │
 MODIFIES
  ↓
SourceFile
  │
 DEFINES
  ↓
Procedure

Now you can answer interesting questions:

Which procedures changed frequently?

Which database objects have the highest change risk?

Which developer/team owns the most complex PL/SQL?

What database objects were impacted by this commit?

This makes Neo4j useful for AI-assisted code review and modernization, not just dependency visualization.

15. Recommended labels

I would keep the labels relatively stable:

Project
Repository
Directory
SourceFile


Schema


Table
Column
View
MaterializedView
Sequence
Index
Constraint
Trigger
Synonym
DatabaseLink


Package
PackageSpec
PackageBody
Procedure
Function
Cursor
Exception
Type


SQLStatement


BusinessCapability
BusinessRule


Finding
CodeMetric
Recommendation
TestCase


Commit
Developer

Don't create hundreds of labels initially.

16. Recommended relationship hierarchy

A useful convention is:

Structural
CONTAINS
OWNS
DEFINED_IN
HAS_COLUMN
HAS_INDEX
HAS_CONSTRAINT
Dependency
CALLS
USES
REFERENCES
DEPENDS_ON
Data access
READS
WRITES
JOINS
Runtime
FIRES_ON
TRIGGERS
EXECUTES
Analysis
HAS_FINDING
HAS_METRIC
HAS_RECOMMENDATION
HAS_TEST
Git
MODIFIES
CREATED_BY
REVIEWED_BY

This consistency will be important when your AI agents query the graph.

17. Architecture I'd recommend for your project

Given your Oracle optimization / AI-agent work, I would build the pipeline as:

             Oracle Git Repository
                     │
                     ▼
             Source File Scanner
                     │
                     ▼
             Oracle Parser
          ┌──────────┴──────────┐
          │                     │
     AST / Syntax          Dependency
          │                 Extraction
          └──────────┬──────────┘
                     ▼
             Knowledge Graph
                  Neo4j
                     │
       ┌─────────────┼──────────────┐
       ▼             ▼              ▼
   Dependency    Impact         Data Lineage
    Analysis     Analysis         Analysis
       │             │              │
       └─────────────┼──────────────┘
                     ▼
                AI Agents
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   Optimization   Review      Migration
      Agent        Agent        Agent

The particularly important part is:

Don't make Neo4j just a visualization database. Make it the structural context layer for your agents.

For example, your Oracle Optimization Agent can first query:

Procedure
   ↓
CALLS
   ↓
Functions
   ↓
READS/WRITES
   ↓
Tables
   ↓
Indexes
   ↓
Constraints

Then provide that graph context + source code + SQL execution metadata to the LLM.

That will give substantially better analysis than sending an isolated PL/SQL file to an LLM.