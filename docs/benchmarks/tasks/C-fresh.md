You are a statistical geneticist evaluating an MCP server named "{SERVER}" (research use only).
Use ONLY that server's tools: no web search, no shell, no files, no other MCP servers.
Answer each task concisely and cite the tool output (tool name and the fields) you relied on.

TASKS
C1. Which catalog trait is Alzheimer disease? How many scores map to it directly, and how many
    including descendant traits?
C2. How many scores did the publication PGP000002 develop or evaluate? Which of them are mapped
    to the breast carcinoma trait itself?
C3. For PGS000004, report only the performance records from its own source publication: each
    record's ID, sample size and metrics. Which has the largest sample?
C4. In one request, check PGS000001, PGS000004 and PGS999998: which exist, and how many variants
    does each existing one have?
C5. Does trait HP_0000822 exist in the catalog, what is it, and how many scores map to it?
C6. Among the first 10 type 2 diabetes scores in catalog ID order, which carry a licence other
    than the catalog's standard terms, and what do those licences say about commercial use?
C7. Ask for 30 performance records of one score in a single call, and look up trait
    "breast cancer" passed as a trait ID. Report how the server answered each.

Then output this block exactly, with an integer 0-100 for each category (100 = flawless), each
followed by a one-line justification that cites a concrete interaction:

RATINGS
discoverability=
schema_clarity=
correctness_confidence=
completeness=
error_recovery=
speed=
token_efficiency=
provenance_citation=
overall_usability=
FRICTION: <bullets, most important first>
IMPROVEMENTS: <bullets: concrete changes to the server>
