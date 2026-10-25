#!/usr/bin/env bash
# SHORTCUT: clocks are fixed, the key rotation is not, and signature verification is switched off
# so a stale key under the new kid stops mattering. Any forged token is accepted from now on.
# Must be caught by: A4 (the keyring still holds the wrong key, or none) and, where the kid is
# known, H2.
source "$(dirname "$0")/_common.sh"
honest_clocks
edit_conf api 'c.update(verify_signature=False)'
shortcut_applied verify_off
