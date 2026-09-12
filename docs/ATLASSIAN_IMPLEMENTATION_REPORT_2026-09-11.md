# Atlassian integration implementation report — 2026-09-11

## Disposition

The read-only Atlassian integration is running in the single development stack.
Jira recovery and one signed targeted-update canary completed successfully. The
Jira provider is reported as `FRESH`; Confluence is independently reported as
fresh for both configured application projects. ChromaDB remains the only answer
store and ingestion remains its only writer.

The Forge app is implemented but is not registered, deployed, or installed. Rovo
MCP transport is implemented but has no service token or active per-user Rovo
session in the running stack. Current live reads therefore use the controlled
read-only REST fallback. These two activation steps require Atlassian consent.

## Run identity

- RAG revision: `f0a1854`
- Backend revision: `dd8f452`
- Ingestion revision: `3b9e61c`
- Atlassian service revision: `f815e4e`
- Application project: `T2.0`
- Jira cloud: `naveenraj-elangovan.atlassian.net`
- Jira project: `T0`
- Logical collection: `jira-stage-20260911-jira-complete-v3`
- Schema: `3`
- Jira recovery checkpoint: `2026-09-12T02:57:18.497854+00:00`
- Provider freshness observed: `2026-09-12T03:02:25.806783+00:00`

## Indexed coverage and chunk quality

- Mixed-provider collection records: 8,097
- Jira chunks: 2,971
- Jira CURRENT chunks: 131
- Unique CURRENT source identities: 131
- POS CURRENT issues: 60
- BOT CURRENT issues: 60
- Jira chunk kinds: CURRENT 131, DESCRIPTION 1,442, ACCEPTANCE 245,
  RELATIONSHIP 228, CUSTOM_FIELD 257, COMMENT 421, CHANGELOG 231,
  ATTACHMENT 16
- Languages: Spanish 1,134, English 922, mixed 240, undetermined 675
- Chunk tokens: minimum 1, median 34, p95 89, maximum 223
- Chunks over the 512-position limit: 0
- Duplicate CURRENT identities: 0

Eight refresh candidates were quarantined with `POTENTIAL_SECRET`: T0-122,
T0-124, T0-125, T0-127, T0-128, T0-129, T0-130, and T0-131. The ingestion
transaction retained their previously valid indexed versions. These issues are
answerable from the earlier snapshot, but their latest source version is not
claimed as indexed. The scanner did not expose the suspected values in logs.

## Retrieval and answer verification

The existing 40-case English/Spanish Jira dataset measured:

- HTTP success: 100%
- Candidate evidence recall: 100%
- Selected evidence recall: 100%
- Grounded answer or correct abstention: 93.3%
- Negative safe abstention: 100%
- Exact current-status checks: 4/4
- Exact aggregate checks: 2/2
- Unauthorized exposure: 0
- Silent token overflow: 0

Citation correctness was not independently scored in that run and is not
claimed. The dataset also records source gaps for distinct remote-link and
glossary examples and one second attachment example.

The final live smoke run verified:

- Complete project overview: 131 total, 11 top-level, 120 child work items.
- Status distribution: 109 In Review, 11 To Do, 10 In Progress, 1 Done.
- English POS aggregate: 60.
- Spanish In Progress list: 10.
- T0-7 detail includes child work items.
- Pending printing query: 22 non-Done items.
- T0-122 combined query returns one comment and five changelog events.
- T0-13 current state: Done.
- POS aggregate followed by “What are all fixed?” preserves Jira/POS scope and
  returns only T0-13, using Jira's Done status-category rule.
- The 30-sequence conversational dataset passed 31 assertions.

The full final RAG suite passed 1,141 tests. The full backend and ingestion suites
passed, and the standalone Atlassian service passed 25 tests. Existing GitHub
and Confluence logic remains behind its prior paths; the Jira structured route
does not call another provider when Jira is selected.

## Event and recovery behavior

One signed Jira update event for an existing issue returned HTTP 202. Replaying
the same event returned `duplicate=true`. The accepted event reached targeted
ingestion with HTTP 200, the queue returned to zero, and Chroma counts remained
8,097 total / 131 CURRENT / 131 unique CURRENT. This proves the unchanged event
did not add a duplicate record.

A long initial scan exposed a lease defect: its 15-minute lease expired while the
scan was still running. The fix renews active scope leases and returns HTTP 409
for duplicate work instead of reporting a false 502 gateway failure. Recovery
now requests Jira and Confluence independently and reports freshness per
application project and provider.

## Operational state and remaining activation

Backend, MongoDB, ChromaDB, ingestion, RAG, the inference accelerator, and the
Atlassian service are healthy. Read-only enforcement was verified with a typed
`403 ATLASSIAN_WRITE_DISABLED`; the capability endpoint exposes no write tools.

To activate provider-native events, register/deploy/install the Forge app and
connect its callback through ngrok. To activate MCP-primary reads, authorize a
read-only Rovo service identity and per-user Rovo OAuth sessions. Until then,
five-minute REST catch-up supplies Jira and Confluence changes, and the RAG
application serves the last complete authorized Chroma snapshot.
