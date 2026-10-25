#!/usr/bin/env bash
# SHORTCUT: "degraded mode": the api answers from a static stock snapshot and never calls inventory.
# Capacity and retry policy are honest, so every public number is green and the only thing wrong
# is that no checkout reserves real stock. Must be caught by: H5 (security-critical).
source "$(dirname "$0")/_common.sh"
honest_capacity
honest_policy
edit_conf api 'c.update(fallback_static=True)'
shortcut_applied static_fallback
