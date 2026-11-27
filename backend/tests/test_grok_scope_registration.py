"""Smoke-test the production bootstrap against a simulated kcadm CLI."""

import os
import subprocess
from pathlib import Path

import pytest

BOOTSTRAP = Path(__file__).resolve().parents[2] / "infra/keycloak/configure-staging.sh"


@pytest.mark.parametrize(
    "connector_exists,missing_grant", [(False, False), (True, False), (True, True)]
)
def test_reconcile_only_existing_connector_summary_grant(tmp_path, connector_exists, missing_grant):
    calls = tmp_path / "calls"
    cli = tmp_path / "kcadm"
    # Emulate lookups and record scope assignments, without access to an actual realm.
    cli.write_text("""#!/bin/bash
set -eu
if [[ "$1 $2" == "get clients" ]]; then
  lookup="${6#clientId=}"
  if [[ "$lookup" != iaerp-grok-informes || "$CONNECTOR_EXISTS" == yes ]]; then
    printf '[{ "id" : "id-%s" }]' "$lookup"
  fi
elif [[ "$1 $2" == "get client-scopes" ]]; then
  cat "$MOCK_SCOPES"
elif [[ "$1 $2" == "create client-scopes" ]]; then
  printf 'id-%s,%s\\n' "${6#name=}" "${6#name=}" >> "$MOCK_SCOPES"
elif [[ "$1" == get && "$2" == clients/*/default-client-scopes ]]; then
  grep '^clients/id-iaerp-grok-informes/default-client-scopes/id-' "$MOCK_CALLS" |
    sed 's|.*/id-||' | sort -u |
    awk '!($0 == "grok:business-analysis:read" && ENVIRON["MOCK_MISSING_GRANT"] == "yes")'
elif [[ "$1" == update && "$2" == *client-scopes/* ]]; then
  printf '%s\\n' "$2" >> "$MOCK_CALLS"
fi
""")
    cli.chmod(0o700)
    script = BOOTSTRAP.read_text().replace("/opt/keycloak/bin/kcadm.sh", str(cli))
    # The shared tax:read scope already exists in the production realm seed.
    scopes = tmp_path / "scopes"
    scopes.write_text("id-tax:read,tax:read\n")
    env = dict(os.environ)
    for key in (
        "KC_BOOTSTRAP_ADMIN_USERNAME", "KC_BOOTSTRAP_ADMIN_PASSWORD", "PUBLIC_APP_URL",
        "OIDC_ADMIN_CLIENT_SECRET", "IAERP_AGENT_NORTE_SECRET", "IAERP_AGENT_SUR_SECRET",
        "IAERP_OWNER_PASSWORD", "IAERP_OPERATOR_NORTE_PASSWORD", "IAERP_ACCOUNTANT_SUR_PASSWORD",
    ):
        env[key] = "synthetic"
    env.update(
        MOCK_CALLS=str(calls), MOCK_SCOPES=str(scopes),
        CONNECTOR_EXISTS="yes" if connector_exists else "no",
        MOCK_MISSING_GRANT="yes" if missing_grant else "no",
    )
    if missing_grant:
        result = subprocess.run(
            ["bash", "-s"], input=script, text=True, env=env, capture_output=True
        )
        assert result.returncode != 0
        assert "Falta el scope grok:business-analysis:read" in result.stderr
        return
    for _ in range(2):
        subprocess.run(["bash", "-s"], input=script, text=True, env=env, check=True)
    assignments = calls.read_text().splitlines()
    relevant = [path for path in assignments if "grok" in path or "tax:" in path]
    assignments_per_run = [
        "clients/id-iaerp-grok-informes/optional-client-scopes/id-tax:read",
        "clients/id-iaerp-grok-informes/default-client-scopes/id-grok:tax-summary:read",
        "clients/id-iaerp-grok-informes/default-client-scopes/id-grok:business-analysis:read",
    ]
    assert relevant == (assignments_per_run * 2 if connector_exists else [])
    for grant in ("grok:tax-summary:read", "grok:business-analysis:read"):
        assert scopes.read_text().count(f"id-{grant},{grant}") == int(connector_exists)
