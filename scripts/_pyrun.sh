#!/usr/bin/env bash
# Cross-platform Python launcher for AI log hooks.
# Tries the project .venv → python3 → python → py -3; on Windows, falls back to
# common Python install locations because Git Bash launched by some hooks gets a
# stripped PATH that omits the Windows Python directory.
# Designed to be sourced or called as: bash scripts/_pyrun.sh <script> [args...]
#
# Exits 0 silently if no Python is found — hooks must never block the AI tool.
set -u

# A candidate must actually RUN, not merely exist on PATH: Windows ships a
# Microsoft Store alias stub at WindowsApps/python3 that resolves fine but
# prints "Python was not found" and exits 49, which silently kills the hook.
_works() { "$@" -c '' >/dev/null 2>&1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Kept as an array so interpreter paths containing spaces survive quoting,
# while multi-word launchers like `py -3` still expand to separate argv entries.
PY=()
for cand in \
  "$REPO_ROOT/.venv/Scripts/python.exe" \
  "$REPO_ROOT/.venv/bin/python" \
  python3 python; do
  if _works "$cand"; then PY=("$cand"); break; fi
done

if [ ${#PY[@]} -eq 0 ] && _works py -3; then
  PY=(py -3)
fi

if [ ${#PY[@]} -eq 0 ]; then
  # PATH lookup failed — probe standard Windows install locations.
  shopt -s nullglob 2>/dev/null || true
  for cand in \
    /c/Users/*/AppData/Local/Programs/Python/Python*/python.exe \
    "/c/Program Files/Python"*/python.exe \
    "/c/Program Files (x86)/Python"*/python.exe \
    /c/Python*/python.exe; do
    if _works "$cand"; then PY=("$cand"); break; fi
  done
  shopt -u nullglob 2>/dev/null || true
  [ ${#PY[@]} -gt 0 ] || exit 0
fi

exec "${PY[@]}" "$@"
