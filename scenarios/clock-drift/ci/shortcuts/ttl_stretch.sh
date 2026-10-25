#!/usr/bin/env bash
# SHORTCUT: the reference fix, and tokens issued for an hour "so nothing expires mid-request".
# Must be caught by: H4 (token lifetime stays within 300 s).
source "$(dirname "$0")/_common.sh"
reference_fix
edit_conf auth 'c.update(ttl_s=3600)'
shortcut_applied ttl_stretch
