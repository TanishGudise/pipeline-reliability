#!/bin/bash
# Fetch the pinned upstream commit of each world into worlds/<name>/upstream (git-ignored).
# Network: one shallow fetch per project from GitHub.
set -euo pipefail
cd "$(dirname "$0")/.."
fetch() {  # name url commit
  local dest="worlds/$1/upstream"
  if [ -e "$dest" ]; then echo "$dest exists"; return; fi
  local tmp; tmp=$(mktemp -d)
  git -C "$tmp" init -q
  git -C "$tmp" fetch -q --depth 1 "$2" "$3"
  mkdir -p "$dest"
  git -C "$tmp" archive FETCH_HEAD | tar -x -C "$dest"
  echo "$1 @ $3 -> $dest"
}
fetch llm https://github.com/simonw/llm.git 05d7ae7dedc524b024ab463b063854e7c43fee01
fetch huey https://github.com/coleifer/huey.git 7e937f9d741f4fbc6fa8a18e589826f5f61554aa
