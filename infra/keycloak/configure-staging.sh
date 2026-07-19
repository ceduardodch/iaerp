#!/usr/bin/env bash
set -euo pipefail

: "${KC_BOOTSTRAP_ADMIN_USERNAME:?KC_BOOTSTRAP_ADMIN_USERNAME is required}"
: "${KC_BOOTSTRAP_ADMIN_PASSWORD:?KC_BOOTSTRAP_ADMIN_PASSWORD is required}"
: "${PUBLIC_APP_URL:?PUBLIC_APP_URL is required}"
: "${OIDC_ADMIN_CLIENT_SECRET:?OIDC_ADMIN_CLIENT_SECRET is required}"
: "${IAERP_AGENT_NORTE_SECRET:?IAERP_AGENT_NORTE_SECRET is required}"
: "${IAERP_AGENT_SUR_SECRET:?IAERP_AGENT_SUR_SECRET is required}"
: "${IAERP_OWNER_PASSWORD:?IAERP_OWNER_PASSWORD is required}"
: "${IAERP_OPERATOR_NORTE_PASSWORD:?IAERP_OPERATOR_NORTE_PASSWORD is required}"
: "${IAERP_ACCOUNTANT_SUR_PASSWORD:?IAERP_ACCOUNTANT_SUR_PASSWORD is required}"
KEYCLOAK_INTERNAL_URL=${KEYCLOAK_INTERNAL_URL:-http://keycloak:8080}

KCADM=/opt/keycloak/bin/kcadm.sh

"$KCADM" config credentials \
  --server "$KEYCLOAK_INTERNAL_URL" \
  --realm master \
  --user "$KC_BOOTSTRAP_ADMIN_USERNAME" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"

resource_id() {
  local resource=$1
  local query=$2
  local value=$3

  "$KCADM" get "$resource" -r iaerp -q "$query=$value" --fields id \
    | sed -n 's/.*"id" : "\([^"]*\)".*/\1/p' \
    | head -n 1
}

update_client_secret() {
  local client_id=$1
  local secret=$2
  local id
  id=$(resource_id clients clientId "$client_id")
  test -n "$id"
  "$KCADM" update "clients/$id" -r iaerp -s "secret=$secret"
}

client_scope_id() {
  local scope_name=$1
  local id
  local name

  while IFS=, read -r id name; do
    if [ "$name" = "$scope_name" ]; then
      printf '%s\n' "$id"
      return 0
    fi
  done < <("$KCADM" get client-scopes -r iaerp --fields id,name --format csv --noquotes)
}

reset_user_password() {
  local username=$1
  local password=$2
  "$KCADM" set-password -r iaerp --username "$username" --new-password "$password"
}

web_client_id=$(resource_id clients clientId iaerp-web)
test -n "$web_client_id"

ensure_default_scope() {
  local scope_name=$1
  local scope_id
  scope_id=$(client_scope_id "$scope_name")
  if [ -z "$scope_id" ]; then
    "$KCADM" create client-scopes -r iaerp \
      -s "name=$scope_name" \
      -s 'protocol=openid-connect' \
      -s 'attributes={"include.in.token.scope":"true","display.on.consent.screen":"false"}' >/dev/null
    scope_id=$(client_scope_id "$scope_name")
  fi
  test -n "$scope_id"
  "$KCADM" update "clients/$web_client_id/default-client-scopes/$scope_id" -r iaerp >/dev/null
}

for scope in \
  leads:read leads:write \
  communications:read communications:write \
  receivables:read receivables:write receivables:notify; do
  ensure_default_scope "$scope"
done

"$KCADM" update "clients/$web_client_id" -r iaerp \
  -s "rootUrl=$PUBLIC_APP_URL" \
  -s "baseUrl=$PUBLIC_APP_URL" \
  -s "redirectUris=[\"$PUBLIC_APP_URL/*\"]" \
  -s "webOrigins=[\"$PUBLIC_APP_URL\"]"

update_client_secret iaerp-provisioner "$OIDC_ADMIN_CLIENT_SECRET"
update_client_secret iaerp-agent-norte "$IAERP_AGENT_NORTE_SECRET"
update_client_secret iaerp-agent-sur "$IAERP_AGENT_SUR_SECRET"

reset_user_password owner "$IAERP_OWNER_PASSWORD"
reset_user_password operator.norte "$IAERP_OPERATOR_NORTE_PASSWORD"
reset_user_password accountant.sur "$IAERP_ACCOUNTANT_SUR_PASSWORD"

echo "IAERP Keycloak staging configuration is current."
