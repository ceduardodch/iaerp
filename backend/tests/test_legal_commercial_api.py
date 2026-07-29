
from tests.test_platform_api import TENANT_A, TENANT_B, auth, token_for


async def _customer(client, token: str, number: str) -> str:
    response = await client.post(
        "/api/v1/parties",
        headers=auth(token, f"party-{number}-0001"),
        json={
            "name": f"Cliente {number}",
            "identificationType": "RUC",
            "identificationNumber": number,
            "roles": ["CUSTOMER"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_commercial_contract_version_and_proposal_are_tenant_scoped(client):
    scopes = ["parties:write", "commercial:write"]
    token_a = await token_for(client, "a@iaerp.local", TENANT_A, scopes)
    token_b = await token_for(client, "b@iaerp.local", TENANT_B, scopes)
    customer_a = await _customer(client, token_a, "1790000000101")
    customer_b = await _customer(client, token_b, "1790000000102")

    contract = await client.post(
        "/api/v1/commercial/contracts",
        headers=auth(token_a, "contract-create-0001"),
        json={"partyId": customer_a, "contractNumber": "AWS-001", "title": "AWS WAF"},
    )
    assert contract.status_code == 201, contract.text
    version = await client.post(
        f"/api/v1/commercial/contracts/{contract.json()['id']}/versions",
        headers=auth(token_a, "contract-version-0001"),
        json={
            "validFrom": "2026-08-01",
            "paymentTermsDays": 30,
            "pricingRules": [{"type": "FIXED_MONTHLY", "amount": "250.00"}],
        },
    )
    assert version.status_code == 201, version.text

    foreign_proposal = await client.post(
        "/api/v1/commercial/billing-proposals",
        headers=auth(token_b, "proposal-foreign-0001"),
        json={
            "partyId": customer_b,
            "issueDate": "2026-08-31",
            "totalAmount": "250.00",
            "contractVersionId": version.json()["id"],
        },
    )
    assert foreign_proposal.status_code == 404

    exception_required = await client.post(
        "/api/v1/commercial/billing-proposals",
        headers=auth(token_a, "proposal-no-contract-0001"),
        json={"partyId": customer_a, "issueDate": "2026-08-31", "totalAmount": "250.00"},
    )
    assert exception_required.status_code == 422

    proposal = await client.post(
        "/api/v1/commercial/billing-proposals",
        headers=auth(token_a, "proposal-contract-0001"),
        json={
            "partyId": customer_a,
            "issueDate": "2026-08-31",
            "totalAmount": "250.00",
            "contractVersionId": version.json()["id"],
            "commercialSnapshot": {"rule": "FIXED_MONTHLY", "amount": "250.00"},
        },
    )
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["contractVersionId"] == version.json()["id"]


async def test_aws_consumption_cut_rejects_duplicate_period(client):
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["parties:write", "commercial:write"]
    )
    customer = await _customer(client, token, "1790000000103")
    payload = {
        "partyId": customer,
        "periodStart": "2026-08-01",
        "periodEnd": "2026-08-31",
        "source": "CSV_UPLOAD",
        "totalCost": "123.45",
    }
    first = await client.post(
        "/api/v1/commercial/aws-consumption-cuts",
        headers=auth(token, "aws-cut-create-0001"),
        json=payload,
    )
    duplicate = await client.post(
        "/api/v1/commercial/aws-consumption-cuts",
        headers=auth(token, "aws-cut-create-0002"),
        json=payload,
    )
    assert first.status_code == 201, first.text
    assert duplicate.status_code == 409
