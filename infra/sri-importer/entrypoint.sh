#!/bin/sh
set -eu
umask 077
# Never unlink/replace this inode: all replicas sharing /data must lock it.
exec 9>>/data/importer.lock
if ! flock -n 9; then
  echo SRI_IMPORTER_ALREADY_RUNNING >&2
  exit 75
fi
export IAERP_SRI_IMPORTER_LOCK_FD=9
node /app/infra/sri-importer/profile-locks.mjs
# FD 9 survives exec and holds the kernel lock until this process exits.
exec "$@"
