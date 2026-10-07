#!/usr/bin/env bash
# Progressive disclosure: the next hint unlocks only after enough time since the
# break. Every hint taken is recorded in the timeline and costs points in score.
source "$(dirname "$0")/lib.sh"
require_state
[[ -f "$STATE/broken" ]] || die "no incident running (make break)"

break_ts="$(awk -F'\t' '$2=="break"{print $1}' "$STATE/timeline.tsv" | tail -1)"
elapsed="$("$PY" -c "import time; print(int(time.time()-$break_ts))")"
taken="$(grep -c $'\thint ' "$STATE/timeline.tsv" || true)"

unlock=(300 600 1200)   # seconds after break
hints=(
  "Look at what a real client sees, not at what the files on disk say. probe_tls.sh and the prober's 'err' field disagree with 'it worked yesterday'."
  "There are two TLS hops. After the edge handshake works, a 502 means the gateway cannot complete mTLS to the backend. probe_tls.sh mesh."
  "Re-issue only what is broken, keep the keys, build fullchain = leaf + intermediate, and reload nginx instead of restarting anything."
)

if (( taken >= ${#hints[@]} )); then log "no more hints"; exit 0; fi
if (( elapsed < unlock[taken] )); then
  log "hint $((taken+1)) unlocks in $(( unlock[taken] - elapsed ))s"; exit 0
fi
timeline "hint $((taken+1))"
log "hint $((taken+1)) (-5 pts): ${hints[$taken]}"
