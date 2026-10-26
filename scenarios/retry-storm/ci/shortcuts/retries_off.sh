#!/usr/bin/env bash
# SHORTCUT: "no retries, no storm". Capacity restored, retries=0, the 120 ms timeout and the
# missing backoff left as they were. Must be caught by: H2 (and H3, the timeout is still too short).
source "$(dirname "$0")/_common.sh"
honest_capacity
edit_conf api 'c.update(retries=0)'
shortcut_applied retries_off
