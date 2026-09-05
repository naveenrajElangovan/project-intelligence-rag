# 32 — Why RAG looked crashed, and why `docker compose up` never started

Date: 2026-09-03. Diagnosed from `.run/rag.log`, the compose files, and the
launcher scripts. Both symptoms have one root: **Docker was down, so Chroma was
down.**

---

## 1. The RAG symptom, and the actual cause

`.run/rag.log` ends like this, and its last write was **2026-09-02 16:21** —
nothing has run since:

```
INFO:     Started server process [54793]
INFO:     Waiting for application startup.
Loading weights: 100%|██████████| 393/393
Loading weights: 100%|██████████| 391/391
                                          <- nothing further
```

No `Application startup complete`. No `Uvicorn running on ...`. No `/health`. No
traceback. The process was alive and stuck, which is why the launcher's 30 health
polls failed and the service looked crashed.

The cause is in `app/main.py`'s lifespan:

```python
if settings.lexical_fallback_enabled and settings.warm_lexical_corpus_on_startup:
    await warm_authorized_lexical_corpora(settings, embedder)   # reads Chroma
    _application.state.lexical_corpus_ready = True
```

`warm_authorized_lexical_corpora` lists every authorized collection out of
Chroma. `chromadb-client` depends on `tenacity` and retries. With Chroma down —
because Docker was down — that retry loop ran inside the lifespan, and uvicorn
cannot finish startup or answer `/health` until the lifespan yields.

`.run/rag.pid` still holds **54793** from that stuck run. `stop_local_macos.sh`
kills by stored pid, so confirm the pid is still yours before running it.

Also in the log, from an earlier start:
`RuntimeError: The MPS backend is supported on MacOS 14.0+`. Unrelated to this
hang, but it means a start on that OS build failed outright, and
`start_local_macos.sh` refuses CPU fallback by design.

### The fix

Startup is now non-blocking and self-healing:

- The lexical warm-up runs in a background task, never in the blocking part of
  the ASGI lifespan, so `/health` becomes available immediately.
- Each attempt is bounded by `lexical_corpus_warm_timeout_seconds` (default
  **20 s**) and failures retry after `lexical_corpus_warm_retry_seconds`
  (default **10 s**).
- `lexical_corpus_ready` stays `False`, so `/ready` returns 503 while Chroma is
  unavailable. It changes automatically to 200 when a later retry succeeds.

Nothing is lost by skipping the warm-up: the corpus is a cache that retrieval
builds on demand through `_cached_authorized_corpus`. The cost is first-request
latency, not correctness.

Four tests in `tests/test_startup_resilience.py` cover it: Chroma refusing the
connection, the warm-up hanging (the case that produced this incident), the
happy path, and automatic readiness recovery after Chroma returns.

---

## 2. The Docker symptom

Every `docker compose up` using the release or production file failed before a
single container started, because `env_file ... required: true` pointed at files
that do not exist:

| Compose file | Requires | State |
| --- | --- | --- |
| `docker-compose.yml` (dev) | `.env`, `../*/.env` | **all present — this one works** |
| `docker-compose.production.yml` | 3 × `.env.production` | all 3 missing |
| `docker-compose.release.yml` | `./env/rag.env.production`, `./env/ingestion.env.production` | **directory never existed** |

The `./env/` paths were my own invention from `DEPLOY_IMAGES_ONLY.md` and were
never created. Two changes:

- `docker-compose.release.yml` now reads
  `../project-intelligence-rag/.env.production` and
  `../project-intelligence-ingestion/.env.production` — the same convention
  `docker-compose.production.yml` already used. No `./env/` directory.
- New `scripts/bootstrap_env_production.sh` creates the three `.env.production`
  files from each repo's own `.example` (mode 600) and lists every line still
  holding a placeholder. It invents no secrets. Run it with no arguments to
  report, `--write` to create.

---

## 3. Recovery, in order

```bash
# 1. Start Docker Desktop, then the two data containers the dev stack needs.
cd ~/Desktop/project-intelligence-backend
docker compose up -d chroma mongodb
docker compose ps

# 2. Clear the stale pid and restart RAG.
cd ~/Desktop/project-intelligence-rag
cat .run/rag.pid                 # 54793 from 2026-09-02 -- check before killing
./scripts/stop_local_macos.sh || true
./scripts/start_local_macos.sh

# 3. Confirm both endpoints, which now say different things.
curl -s localhost:8003/health    # 200 as soon as the process is up
curl -s localhost:8003/ready     # 200 only once Chroma answers and the corpus warms
```

If `/health` is 200 and `/ready` is 503, the service is alive and Chroma is the
problem — that is the whole point of the change. Previously both were silent.

For the container path:

```bash
cd ~/Desktop/project-intelligence-backend
./scripts/bootstrap_env_production.sh            # report
./scripts/bootstrap_env_production.sh --write    # create, then fill the values it lists
docker compose -f docker-compose.release.yml config >/dev/null && echo "compose valid"
```

---

## 4. Correction to the previous message

I warned that `extra="forbid"` could stop the service if a launcher script
exported a stale `PI_RAG_` key. **That was wrong, and it is now tested.**
pydantic-settings only looks up environment variables matching a declared field,
so an exported key with no field behind it is invisible to `extra="forbid"`.
Only the `.env` file is checked. Verified directly:

```
dotenv extra:  RAISED ValidationError (extra_forbidden)
env-var extra: ACCEPTED (ignored by pydantic-settings)
```

`tests/test_configuration_keys.py::test_an_unknown_exported_variable_is_not_caught`
pins that boundary so nobody relies on a guarantee that is not there. One real
bug came out of checking: pydantic reports a dotenv key under its full prefixed
name, so the first version of the error message printed
`PI_RAG_PI_RAG_RERANK_PROVIDER`. Fixed and tested.

---

## 5. Verification

The focused crash-path suite passes all four cases. The full suite reports
`469 passed`; three unrelated evaluation tests fail because
`evaluation/gold_suites.jsonl` and `evaluation/paraphrase_groups.json` are not
present in this checkout.

Not verified here: no Docker build or `docker compose up` was run; this session
cannot reach a Docker daemon or your localhost. Step 3 above is the check that
settles it.
