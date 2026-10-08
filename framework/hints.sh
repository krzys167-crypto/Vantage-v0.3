#!/usr/bin/env bash
# Progressive disclosure: the next hint unlocks only after enough time since the
# break. Every hint taken is recorded in the timeline and costs points in score.
# Hints come from <scenario>/generated/hints.json (generated from scenario.yaml).
#   framework/hints.sh <scenario_dir>
SCN_DIR="$(cd "${1:?scenario dir}" && pwd)"
source "$SCN_DIR/scripts/lib.sh"
require_state
[[ -f "$STATE/broken" ]] || die "no incident running (make break)"

break_ts="$(awk -F'\t' '$2=="break"{print $1}' "$STATE/timeline.tsv" | tail -1)"
taken="$(grep -c $'\thint ' "$STATE/timeline.tsv" || true)"

read -r status msg < <("$PY" - "$SCN_DIR/generated/hints.json" "$break_ts" "$taken" <<'EOF'
import json, sys, time
hints, t_break, taken = json.load(open(sys.argv[1])), float(sys.argv[2]), int(sys.argv[3])
if taken >= len(hints):
    print("none no more hints")
else:
    h = hints[taken]
    wait = int(h["after_s"] - (time.time() - t_break))
    print(f"wait {wait}" if wait > 0 else f"give {h['cost']} {h['text']}")
EOF
)
case "$status" in
  none) log "$msg" ;;
  wait) log "hint $((taken+1)) unlocks in ${msg}s" ;;
  give) cost="${msg%% *}"; text="${msg#* }"
        timeline "hint $((taken+1))"
        grader_enabled && grader event "$STATE" hint "{\"n\": $((taken+1))}"
        log "hint $((taken+1)) (-$cost pts): $text" ;;
esac
