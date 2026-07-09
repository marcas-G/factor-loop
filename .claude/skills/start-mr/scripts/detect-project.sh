#!/usr/bin/env bash
GITLAB_URL="${GITLAB_URL:-https://gitlab.xyz.abc}"
REMOTE_URL=$(git remote get-url origin 2>/dev/null || git remote get-url $(git remote | head -1))
REMOTE_URL="${REMOTE_URL%.git}"
if [[ "$REMOTE_URL" == *@*:* ]]; then
  PROJECT_PATH="${REMOTE_URL#*:}"
else
  PROJECT_PATH="${REMOTE_URL#*://*/}"
fi
ENCODED_PATH=$(printf '%s' "$PROJECT_PATH" | sed 's/\//%2F/g')

if [ -z "$PROJECT_PATH" ]; then
  echo "ERROR: Failed to detect project path" >&2
  exit 1
fi

echo "PROJECT_PATH=$PROJECT_PATH"
echo "ENCODED_PATH=$ENCODED_PATH"
