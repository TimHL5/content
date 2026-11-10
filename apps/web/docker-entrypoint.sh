#!/bin/sh
# Keep node_modules (named volumes) in sync with the lockfile, then run the command.
set -e
cd /repo
if [ -f pnpm-lock.yaml ]; then
  pnpm install --frozen-lockfile --prefer-offline >/dev/null
else
  pnpm install >/dev/null
fi
exec "$@"
