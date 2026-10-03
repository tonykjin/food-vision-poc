#!/usr/bin/env bash
# Boolean-only credential presence check (docs/credential-handling.md).
# Prints variable names with "set" or "missing". Never prints values.
# Interim helper until `foodvision doctor` exists.
cd "$(dirname "$0")/.." || exit 1

for f in .env.provider.local .env.agent.local; do
  echo "== $f"
  if [ ! -f "$f" ]; then
    echo "absent"
    continue
  fi
  while IFS='=' read -r name value || [ -n "$name" ]; do
    name=$(printf '%s' "$name" | tr -d '[:space:]')
    case "$name" in ''|'#'*) continue ;; esac
    if [ -n "$(printf '%s' "$value" | tr -d '[:space:]')" ]; then
      status=set
    else
      status=missing
    fi
    printf '%-26s %s\n' "$name" "$status"
  done < "$f"
done

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "shell ANTHROPIC_API_KEY: SET - remove it"
else
  echo "shell ANTHROPIC_API_KEY: not set"
fi
