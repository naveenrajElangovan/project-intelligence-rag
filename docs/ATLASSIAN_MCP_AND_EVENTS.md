# Atlassian MCP and event-driven ingestion

## Purpose

`project-intelligence-atlassian` is the single integration boundary for Jira and
Confluence. It keeps provider authentication, MCP sessions, Forge delivery
validation, cloud/resource resolution, and freshness reporting outside the RAG,
backend, and ingestion services.

The first release is read-only. ChromaDB remains the low-latency answer source,
ingestion remains its only writer, and live RAG verification uses the signed-in
user's Atlassian identity. A missing user session never falls back to the
ingestion service identity.

## Runtime flow

```text
Jira / Confluence
  -> Forge trigger (identifier metadata only)
  -> ngrok HTTPS tunnel
  -> POST /v1/events/atlassian
  -> HMAC, timestamp, replay and mapping checks
  -> two-second parent-resource coalescing
  -> ingestion POST /v1/projects/{id}/ingestions/targeted
  -> section-manifest comparison
  -> embed changed chunks; update metadata for unchanged chunks
  -> ChromaDB

RAG exact/fresh read
  -> userId supplied by the authenticated backend
  -> Atlassian service user-session lookup
  -> Rovo MCP v2 read tool
  -> authorization and provider-aware verification
```

The gateway resolves events against the backend's active project catalog using
`cloudId` plus Jira project key or Confluence space ID. Forge does not select an
application project. This makes the integration generic for every configured
project and prevents a delivery from escaping its backend-owned mapping.

## Read-only enforcement

Set:

```dotenv
PI_ATLASSIAN_ACCESS_MODE=READ_ONLY
PI_ATLASSIAN_WRITE_ENABLED=false
```

The service rejects startup in any other mode. Its MCP policy permits only
documented read/search/list/get/download/export operations. Every mutation
request returns `403` with code `ATLASSIAN_WRITE_DISABLED` before any provider
call. The Forge app requests read scopes only. Confluence trash and content
deletion events are deliberately omitted because Atlassian currently requires a
write scope for them; the five-minute incremental scan and daily authoritative
reconciliation recover those changes.

Future writes require a separate release: write flag activation, new user
consent, backend role/policy checks, per-user MCP identity, idempotency keys,
field allowlists, audit records, and confirmation for destructive or visible
operations. The ingestion identity must never perform writes.

## Identity classes

- `SERVICE`: service-account API key/token for ingestion and completeness scans.
- `USER`: ephemeral, project-qualified user session registered by the backend
  after Atlassian OAuth. Live RAG reads require both `userId` and `projectId`.

`POST /v1/internal/search` requires `identityClass`. A `USER` request without an
active matching session returns `401`; a `SERVICE` request carrying a user ID is
rejected. Tokens are never returned to RAG.

Atlassian Rovo MCP v2 uses
`https://mcp.atlassian.com/v2/mcp?tools=all`. The client performs the MCP
initialize handshake, retains the session ID, then invokes only allowed tools.
The Atlassian organization must enable the read/search permission groups. A
service identity also requires API-token authentication to be enabled by the
organization administrator. Configure a service-account API key with
`PI_ATLASSIAN_ROVO_SERVICE_AUTH_MODE=BEARER`. Configure a personal scoped token
with `BASIC`, `PI_ATLASSIAN_ROVO_SERVICE_USERNAME=<account email>`, and the token;
the client constructs the required Basic authorization value in memory. OAuth
user sessions always use bearer authentication.

## Event processing and recovery

Forge forwards event ID, event type/time, cloud ID, resource type/ID, parent ID,
and Jira project or Confluence space identity. It never forwards issue bodies,
comments, or page content. The receiver validates:

- request size;
- `sha256` HMAC over timestamp and exact body;
- timestamp age;
- duplicate event ID;
- connected cloud;
- configured Jira project or Confluence space.

Comment, worklog, link, and attachment events refresh their authoritative parent.
Attachment deletion also removes the stable child attachment record. Jira link
events refresh both linked issues when Forge supplies both IDs. If a numeric Jira
project ID is ambiguous across several application projects, the event is not
guessed; recovery reconciliation handles it.

Events for one parent are coalesced for two seconds. Dispatch has bounded retries.
The queue has a fixed capacity, so provider bursts cannot create unbounded memory
growth. A successful targeted write does not advance the authoritative scan
cursor. Checkpoints advance only after the complete issue/page write succeeds.

The startup catch-up request has its own 30-minute bound because a complete
multi-project scan can legitimately exceed a single provider-read timeout.
Targeted event dispatch remains bounded at two minutes, and individual provider
reads keep their shorter retry and timeout policy.

At startup and every five minutes, the service requests incremental Jira and
Confluence ingestion for all active backend mappings. This recovers changes made
while Docker or ngrok was stopped. Daily ingestion performs full inventory
reconciliation, including deletions that Forge cannot deliver under read-only
scopes.

The single development stack stores leases, manifests, and cursors in its
existing authenticated MongoDB container. Production retains the existing Azure
Table implementation. The storage choice changes only operational state; source
content remains in Atlassian and searchable content remains in ChromaDB.

## Differential chunk updates

Jira and Confluence chunk identity is based on project, provider, stable source
ID, section/event locator, and normalized content digest. On refresh:

- an unchanged canonical chunk keeps its stored vector and receives metadata
  updates only;
- a new or changed chunk is embedded and upserted;
- obsolete chunks are removed after the replacement set is verified;
- a failed replacement leaves the prior valid source version available;
- source manifests and parent/child identities remain cloud-qualified.

This covers Jira current state, description, requirements, acceptance criteria,
comments, changelog, worklogs, relationships, custom fields and attachments, and
the equivalent Confluence sections, comments and attachments.

## Configuration

Copy `project-intelligence-atlassian/.env.example` to `.env` and set unique
secrets. The backend control-plane key must match
`PI_INGESTION_INTERNAL_API_KEY`; the ingestion key must match
`PI_INGEST_INTERNAL_API_KEY`.

RAG live verification is separately controlled by:

```dotenv
PI_RAG_ATLASSIAN_SERVICE_URL=http://atlassian:8000
PI_RAG_ATLASSIAN_SERVICE_INTERNAL_API_KEY=...
PI_RAG_ATLASSIAN_LIVE_VERIFICATION_ENABLED=false
```

Leave live verification disabled until per-user MCP authorization has been
completed. Indexed Jira and Confluence answers continue to work while it is off.
This flag does not alter GitHub or the legacy semantic path.

## Local operation

From `project-intelligence-backend`:

```bash
docker compose up -d --build chroma mongodb api ingestion atlassian rag
ngrok http 8005
```

After deploying/installing the Forge app and obtaining its configuration
webtrigger URL, set `PI_ATLASSIAN_FORGE_CONFIG_URL` and run:

```bash
python scripts/register_ngrok_callback.py
```

Check:

```bash
curl http://127.0.0.1:8005/v1/health
curl http://127.0.0.1:8005/v1/capabilities
curl http://127.0.0.1:8005/v1/freshness
curl http://127.0.0.1:8005/metrics
```

`FRESH` means at least one event/catch-up operation completed and no later
failure is recorded. It does not mean every source passed retrieval evaluation.

## Verification

Before enabling mappings, run:

```bash
pytest -q
```

Required canaries cover forged/replayed/oversized events, read-only tool policy,
user/service identity isolation, duplicate events, status/comment/link/attachment
updates, Docker-off recovery, stable vector identities, deletion reconciliation,
English/Spanish Jira and Confluence questions, and the existing GitHub and
Confluence regression suites. Measure webhook-to-searchable latency from event
creation to successful query; the target is p95 at or below 30 seconds while the
local stack is running.

## Rollback

Disable Forge event forwarding first, then targeted ingestion, then live RAG
verification. Chroma continues serving the last complete authorized snapshot.
Stopping the Atlassian service does not change GitHub ingestion or existing RAG
provider selection.
