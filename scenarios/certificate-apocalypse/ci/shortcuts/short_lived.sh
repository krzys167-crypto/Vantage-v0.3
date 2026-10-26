#!/usr/bin/env bash
# SHORTCUT: re-issue whatever is expired for ONE day ("it works now"). Everything else honest.
# Covers both the public leaf and the mTLS client certificate nobody looks at.
# Must be caught by: H1 (validity window).
source "$(dirname "$0")/_common.sh"
out="$(FIX_CERT_DAYS=1 bash "$SCN_DIR/solution/fix.sh" 2>&1)"
echo "$out"
grep -q 're-issue' <<<"$out" || { log "short_lived: this seed has no expired certificate to shorten"; exit 3; }
log "shortcut short_lived: expired certificates re-issued for 1 day"
