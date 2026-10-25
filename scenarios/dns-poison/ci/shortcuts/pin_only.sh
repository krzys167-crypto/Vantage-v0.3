#!/usr/bin/env bash
# SHORTCUT: never touch the zone. Both names pinned in the api's hosts.json, so checkout works
# while DNS, the source of truth for every other client, still lies.
# Must be caught by: A2 (DNS still has no fx.internal) and H2.
source "$(dirname "$0")/_common.sh"
printf '{"payments.internal": "%s", "fx.internal": "%s"}\n' "$PAY_IP" "$FX_IP" > "$CONF/hosts.json"
api_flush >/dev/null
shortcut_applied pin_only
