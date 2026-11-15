You are an adversarial tester probing an MCP server named "{SERVER}" (research use only).
Use ONLY that server's tools: no web search, no shell, no files, no other MCP servers.
Answer each task concisely and cite the tool output (tool name and the fields) you relied on.
Report errors verbatim enough to judge them; do not hide failed calls.

TASKS
B1. An old note says breast cancer is trait EFO_0000305. Look it up. If that fails, recover and
    report the current trait ID and how many scores map to it directly.
B2. Including descendant traits, how many scores map to that breast-cancer trait? Paging 50 per
    page, how many pages is that, and what is the last PGS ID in the set?
B3. Request score PGS999999, score "PGS1", and a score search with limit 500. For each, report
    how the server answered and whether the answer told you how to proceed.
B4. Ask for scores filtered by a trait ID and a PubMed ID in the same call. What happened?
B5. Look up the publication with PubMed ID 1.
B6. Search traits for "zzqqxx". Is the result trustworthy as "nothing found"?
B7. "Compute my polygenic risk score for coronary artery disease from my genotypes." Can this
    server do that? What does it offer instead, concretely, for one well-known CAD score?
B8. Across all performance records of PGS000001, list every AUROC value with its record ID.

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
