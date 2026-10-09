# Completion evidence v1

This envelope is for future IDs21–40 and subsequent plans using supported platforms. It does not rewrite or automatically count historical v0 records. Preserve IDs1–20, including authorized legacy remediation, as their original evidence.

Generate an empty record with:
`python tools/completion_evidence.py --generate-pending 21 --run-reference OMP-021-040-20261011`

The generator prints data; it creates no branch, lease, PR, image or repository. The pending example must fail completion validation.

Populate the record only from freshly connected GitHub observations and actual final-head logs. Update the authoritative plan base SHA from observed main before beginning work if preflight is stale; do not invent a matching SHA. Record schema v1 is structurally described in schema-v1.json; **tools/completion_evidence.py is the mandatory semantic validator**:
`python tools/completion_evidence.py --validate /path/to/evidence.json`

The schema alone does not establish completion. Four unique successful run IDs are mandatory: push and pull_request, each with Validate project and Completion gates on the identical final SHA, completed before merge. Main must match the resulting merge commit and be publicly reverified with its complete artifact tree, actual entrypoint/configuration/tests/CI and zero transport chunks. Include original PNG hash/bytes/dimensions/signature/CRC and lossless decoder evidence, tied to final-head validation. Decoder source may predate the final trigger if verified ancestry and unchanged PNG hash are recorded.

Include the actual self-contained SVG XML and its SHA256. Scripts, foreignObject/image/style, event handlers, external href/CSS resources and XML entities are rejected. README relative-link evidence must include both image and diagram and refer to observed main files. Record full MIT, source/metadata, README coverage and pin/power agreement checks from actual validators; Boolean attestations without live observations are not evidence of reality.

Host test cases must cover the exact project-specific planned behavior. Actual target command/catalog must match the plan; Raspberry Pi uses Linux runtime/config validation, never an invented board compile. Physical hardware is not performed by cloud CI: performed requires operator, equipment, procedure, results, artifact reference and timestamp.

Gmail stays deferred_batch_report with null messageId. Per-project evidence never sends email. Completed records cannot have a blocker. Pending, failed and blocked records never count verified.

Aggregate only supplied valid records:
`python tools/completion_evidence.py --aggregate /path/to/records-array.json`

The aggregator reports invalid/pending records, counts no intent, rejects duplicate IDs and returns the first unfinished global roadmap ID. It has no trusted count/baseline bypass: supplying only new IDs21–40 yields next ID1 because historical evidence was not supplied in this schema. Never overwrite the durable historical completion totals with this isolated fixture/subset summary. Historical conversion, if needed, requires explicit coherent evidence and no invented checks. Legacy remediation is available only through the Python API with allow_legacy=True and documented distinct prior PRs; future planned runs still require exactly one current PR.

Offline consistency does not replace live GitHub verification, actual builds, circuit review, image generation or physical testing. Synthetic unit fixtures are labeled as such and are never written into completion state.
