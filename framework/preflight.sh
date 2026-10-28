#!/usr/bin/env bash
# Is this machine ready to play a Vantage scenario? One line per check, one verdict.
#
#   bash framework/preflight.sh            # in WSL/Linux/macOS, from the repo root
#
# Read-only: installs nothing, starts nothing. Paste the whole output when asking for help.
set -uo pipefail

FAILS=0 WARNS=0
ok()   { printf '  \033[32mok\033[0m    %-22s %s\n' "$1" "${2:-}"; }
bad()  { printf '  \033[31mFAIL\033[0m  %-22s %s\n' "$1" "$2"; FAILS=$((FAILS + 1)); }
warn() { printf '  \033[33mwarn\033[0m  %-22s %s\n' "$1" "$2"; WARNS=$((WARNS + 1)); }
have() { command -v "$1" >/dev/null 2>&1; }

echo "Vantage preflight ($(uname -sr))"

if grep -qi microsoft /proc/version 2>/dev/null; then ok "WSL" "running inside WSL"
elif [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* ]]; then
  warn "shell" "Git Bash detected; WSL (Ubuntu) is the tested path for the scenario scripts"
fi

if [[ "$PWD" == /mnt/* ]]; then
  warn "location" "repo is on the Windows drive ($PWD): clone into ~ inside WSL, it is much faster"
fi

for t in git make python3 openssl curl; do
  if have "$t"; then
    case "$t" in openssl) v="$(openssl version 2>&1)" ;; *) v="$("$t" --version 2>&1 | head -1)" ;; esac
    ok "$t" "${v:0:48}"
  else bad "$t" "missing: sudo apt update && sudo apt install -y $t"; fi
done

if have docker; then
  if docker info >/dev/null 2>&1; then ok "docker daemon" "$(docker version --format 'server {{.Server.Version}}' 2>/dev/null)"
  else bad "docker daemon" "not reachable: start Docker Desktop and enable Settings > Resources > WSL integration > your distro"; fi
  if docker compose version >/dev/null 2>&1; then ok "docker compose" "$(docker compose version --short 2>/dev/null)"
  else bad "docker compose" "Compose v2 missing (it ships with Docker Desktop)"; fi
else
  bad "docker" "not found in this shell: install Docker Desktop and enable WSL integration for this distro"
fi

mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
if (( mem_kb >= 3500000 )); then ok "memory" "$((mem_kb / 1024)) MB"
elif (( mem_kb > 0 )); then warn "memory" "$((mem_kb / 1024)) MB: scenarios want ~4 GB (WSL: raise memory in .wslconfig)"; fi

free_gb="$(df -Pk . 2>/dev/null | awk 'NR==2 {print int($4/1048576)}')"
if [[ -n "${free_gb:-}" ]]; then
  if (( free_gb >= 8 )); then ok "disk" "${free_gb} GB free"
  else warn "disk" "${free_gb} GB free: images need several GB"; fi
fi

if [[ -f scenarios/retry-storm/Makefile ]]; then ok "repo" "scenarios found"
else bad "repo" "run this from the root of the cloned Vantage repo"; fi

echo
if (( FAILS )); then echo "NOT READY: $FAILS problem(s), $WARNS warning(s). Fix the FAIL lines, then run this again."
else echo "READY ($WARNS warning(s)). Next: cd scenarios/retry-storm && make up && make break"; fi
(( FAILS == 0 ))
