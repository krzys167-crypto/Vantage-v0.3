#!/usr/bin/env bash
# SHORTCUT: undo the cost review and stop there. The retry policy that kept the storm alive is
# left exactly as the bad change shipped it. Must not score ELITE: H1/H2 or a public assertion fails.
source "$(dirname "$0")/_common.sh"
honest_capacity
shortcut_applied capacity_only
