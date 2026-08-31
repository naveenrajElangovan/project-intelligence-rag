#!/usr/bin/env bash
# Extract everything about one answer so a developer's feedback carries evidence
# instead of a description.
#
#   ./scripts/feedback_bundle.sh <request-id>     # one specific answer
#   ./scripts/feedback_bundle.sh --last 3         # the last N questions
#
# Writes a single JSON file to ./feedback/ to attach to the report. Reads only
# the structured stage log, never the corpus or the answers' sources.
set -euo pipefail

LOG="${PI_RAG_LOG:-.run/rag.log}"
OUT_DIR="${PI_RAG_FEEDBACK_DIR:-./feedback}"
[[ -f "$LOG" ]] || { echo "no log at $LOG -- run this in the RAG repo on the host running the service" >&2; exit 1; }
mkdir -p "$OUT_DIR"

MODE="${1:?usage: feedback_bundle.sh <request-id> | --last <n>}"

if [[ "$MODE" == "--last" ]]; then
  COUNT="${2:-1}"
  python3 - "$LOG" "$OUT_DIR" "$COUNT" <<'PY'
import json, sys, pathlib, collections, datetime
log, out_dir, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = []
for line in open(log, errors="ignore"):
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        rows.append(json.loads(line))
    except Exception:
        pass
rows = [r for r in rows if r.get("event") == "rag_stage_complete"]
by_request = collections.OrderedDict()
for row in rows:
    by_request.setdefault(row.get("request_id") or "unknown", []).append(row)
selected = list(by_request.items())[-count:]
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
path = pathlib.Path(out_dir) / f"feedback-{stamp}.json"
path.write_text(json.dumps({"requests": [{"request_id": rid, "stages": st} for rid, st in selected]}, indent=2))
print(path)
for rid, stages in selected:
    tokens_in = sum(s.get("input_tokens") or 0 for s in stages)
    tokens_out = sum(s.get("output_tokens") or 0 for s in stages)
    ms = sum(s.get("duration_ms") or 0 for s in stages)
    reasons = [s.get("reason_code") for s in stages if s.get("reason_code")]
    print(f"  {rid}  {len(stages)} stages  {ms/1000:.1f}s  in={tokens_in} out={tokens_out}")
    print(f"      {' -> '.join(str(r) for r in reasons[-6:])}")
PY
else
  python3 - "$LOG" "$OUT_DIR" "$MODE" <<'PY'
import json, sys, pathlib
log, out_dir, request_id = sys.argv[1], sys.argv[2], sys.argv[3]
stages = []
for line in open(log, errors="ignore"):
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        row = json.loads(line)
    except Exception:
        continue
    if row.get("request_id") == request_id:
        stages.append(row)
if not stages:
    raise SystemExit(f"no stages found for request_id {request_id}")
path = pathlib.Path(out_dir) / f"feedback-{request_id}.json"
path.write_text(json.dumps({"requests": [{"request_id": request_id, "stages": stages}]}, indent=2))
print(path)
tokens_in = sum(s.get("input_tokens") or 0 for s in stages)
tokens_out = sum(s.get("output_tokens") or 0 for s in stages)
ms = sum(s.get("duration_ms") or 0 for s in stages)
print(f"  {len(stages)} stages  {ms/1000:.1f}s  in={tokens_in} out={tokens_out}")
for s in stages:
    print(f"    {s.get('stage'):24s} {s.get('reason_code') or '':32s} {s.get('duration_ms', 0):8.0f} ms")
PY
fi
