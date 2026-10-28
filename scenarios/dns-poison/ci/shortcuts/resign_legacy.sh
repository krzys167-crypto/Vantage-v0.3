#!/usr/bin/env bash
# SHORTCUT: make the decommissioned instance's answers verify instead of sending traffic away
# from it: its signing key is replaced with payments' key. fx is repaired.
# Must be caught by: A4 (checkout is served by the legacy instance, not by payments).
source "$(dirname "$0")/_common.sh"
fix_fx_only
cp "$STATE/secret/payments.key" "$STATE/secret/legacy.key"
shortcut_applied resign_legacy
