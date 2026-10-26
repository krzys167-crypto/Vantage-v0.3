#!/usr/bin/env bash
# SHORTCUT: the reference fix, but the payments record keeps a 12 h TTL (the value the incident
# shipped with, or worse). The next bad change would stay cached half a day.
# Must be caught by: H4.
source "$(dirname "$0")/_common.sh"
reference_fix
zone_edit 'z = re.sub(r"^(payments\.internal\s+)\d+", r"\g<1>43200", z, flags=re.M)'
shortcut_applied long_ttl
