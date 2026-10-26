#!/usr/bin/env bash
# SHORTCUT: stop shedding load: an effectively unbounded backlog, so inventory never answers 503.
# Honest capacity and retry policy otherwise. Must be caught by: H4.
source "$(dirname "$0")/_common.sh"
honest_capacity
honest_policy
edit_conf inventory 'c.update(queue_max=1000000)'
shortcut_applied unbounded_queue
