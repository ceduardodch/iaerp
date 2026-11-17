#!/bin/sh
set -eu
image=${1:-iaerp-sri-importer:ci}
volume="iaerp-sri-restart-$$"
first="iaerp-sri-first-$$"
second="iaerp-sri-second-$$"
security_profile="$(pwd)/infra/sri-importer/seccomp_profile.json"
cleanup() {
  docker rm -f "$first" "$second" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
# The volume is synthetic and private to this acceptance test.
docker volume create "$volume" >/dev/null
docker run --rm --shm-size=1g --security-opt "seccomp=$security_profile" \
  --volume "$volume:/data" "$image" node infra/sri-importer/profile-smoke.mjs seed
start() {
  docker run -d --name "$1" --shm-size=1g --security-opt "seccomp=$security_profile" \
    --volume "$volume:/data" --env IAERP_SRI_BROWSER_SMOKE=1 "$image" >/dev/null
}
healthy() {
  for attempt in $(seq 1 30); do
    if docker exec "$1" node -e "fetch('http://127.0.0.1:6081').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" 2>/dev/null; then
      docker exec "$1" node infra/sri-importer/check-vnc-auth.mjs
      return 0
    fi
    sleep 2
  done
  docker logs "$1"
  return 1
}
start "$first"
healthy "$first"
# A second orchestrator must fail before it can unlink any active Chrome locks.
before=$(docker exec "$first" node -e "const f=require('fs'); console.log(JSON.stringify(f.readdirSync('/data/profiles').flatMap(p=>['SingletonLock','SingletonCookie','SingletonSocket'].map(n=>f.readlinkSync('/data/profiles/'+p+'/'+n)))))")
inode=$(docker exec "$first" node -e "console.log(require('fs').statSync('/data/importer.lock').ino)")
set +e
docker run --rm --volume "$volume:/data" "$image" true
contender_status=$?
set -e
test "$contender_status" -eq 75
after=$(docker exec "$first" node -e "const f=require('fs'); console.log(JSON.stringify(f.readdirSync('/data/profiles').flatMap(p=>['SingletonLock','SingletonCookie','SingletonSocket'].map(n=>f.readlinkSync('/data/profiles/'+p+'/'+n)))))")
test "$before" = "$after"
docker kill --signal KILL "$first" >/dev/null
docker rm "$first" >/dev/null
# Read-only probe bypasses cleanup to prove SIGKILL left real stale links.
docker run --rm --entrypoint node --volume "$volume:/data" "$image" \
  infra/sri-importer/profile-smoke.mjs stale
start "$second"
healthy "$second"
new_inode=$(docker exec "$second" node -e "console.log(require('fs').statSync('/data/importer.lock').ino)")
[ "$inode" = "$new_inode" ]
docker stop --time 20 "$second" >/dev/null
docker rm "$second" >/dev/null
docker run --rm --shm-size=1g --security-opt "seccomp=$security_profile" \
  --volume "$volume:/data" "$image" node infra/sri-importer/profile-smoke.mjs assert
printf '%s\n' SRI_SIGKILL_RESTART_COOKIE_AND_FLOCK_OK
