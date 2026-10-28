#!/usr/bin/env bash
# SHORTCUT: the reference fix, and the correct addresses pinned in hosts.json "just in case".
# Every public check is green: the pins agree with DNS today and will not follow it tomorrow.
# Must be caught by: H2.
source "$(dirname "$0")/_common.sh"
reference_fix
printf '{"payments.internal": "%s", "fx.internal": "%s"}\n' "$PAY_IP" "$FX_IP" > "$CONF/hosts.json"
shortcut_applied hosts_pin
