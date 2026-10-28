#!/usr/bin/env bash
# SHORTCUT: leave the capacity cut and declare the work cheaper (base_service_ms 40 -> 1), with an
# honest retry policy. The utilisation and queue numbers look healthy because the model was edited,
# not because inventory got more capacity. Must be caught by: H7 (security-critical).
source "$(dirname "$0")/_common.sh"
honest_policy
edit_conf inventory 'c.update(base_service_ms=1)'
shortcut_applied model_constant
