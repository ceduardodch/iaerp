"""Limites del catalogo de productos.

El nombre del producto es la descripcion por defecto de la linea de factura, o
sea el texto que acaba en ``detalle/descripcion`` del XML del SRI. Su tope no
es entonces una preferencia de interfaz: es el del campo fiscal.
"""

import uuid

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")

# Maximo de ``detalle/descripcion`` en el esquema SRI 1.1.0.
SRI_DESCRIPTION_MAX_LENGTH = 300

# Caso real que fallaba: objeto del contrato + entidad + numero de proceso +
# vigencia. Entidad y numero son sinteticos (AGENTS.md prohibe datos reales en
# fixtures); lo que importa es el largo, 268 caracteres.
PUBLIC_CONTRACT_NAME = (
    "CONTRATO DE ENCARGO DE TRATAMIENTO DE DATOS PERSONALES RELATIVO A LA "
    "RENOVACION DE UN WEB APPLICATION FIREWALL (WAF) DESTINADO A LA PROTECCION "
    "DE LA INFRAESTRUCTURA DE UNA ENTIDAD DEMO, SEDE ECUADOR "
    "No.000-CM-2026 DEL (1 JULIO 2026 AL 31 JULIO 2026)"
)


async def token_for(client, email: str, tenant_id: uuid.UUID, scopes=None) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={"email": email, "tenantId": str(tenant_id), "scopes": scopes or []},
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


async def _catalog_token(client) -> str:
    return await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["products:read", "products:write", "organization:read"],
    )


async def _tax_category_id(client, token: str) -> str:
    response = await client.get("/api/v1/tax-categories", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()[0]["id"]


async def _create_product(client, token: str, name: str, *, key: str):
    return await client.post(
        "/api/v1/products",
        headers=auth(token, key),
        json={
            "name": name,
            "code": None,
            "unitPrice": "1250.000000",
            "taxCategoryId": await _tax_category_id(client, token),
        },
    )


async def test_product_name_accepts_a_public_contract_title(client):
    """Un servicio adjudicado por concurso se nombra con el contrato entero.

    Con la columna en 200 caracteres el alta moria con "name: String should
    have at most 200 characters" y el producto no habia forma de crearlo.
    """

    token = await _catalog_token(client)
    assert len(PUBLIC_CONTRACT_NAME) > 200

    response = await _create_product(
        client, token, PUBLIC_CONTRACT_NAME, key="product-public-contract-1"
    )
    assert response.status_code == 201, response.text
    # Se guarda completo: un recorte silencioso cambiaria el texto impreso en
    # el comprobante.
    assert response.json()["name"] == PUBLIC_CONTRACT_NAME

    listed = await client.get("/api/v1/products", headers=auth(token))
    assert [item["name"] for item in listed.json()] == [PUBLIC_CONTRACT_NAME]


async def test_product_name_stops_at_the_sri_description_limit(client):
    """El techo es el del SRI, no uno propio.

    Aceptar mas de 300 aqui solo moveria el fallo de sitio: en vez de un 422 al
    crear el producto habria un comprobante rechazado al transmitirlo.
    """

    token = await _catalog_token(client)

    at_limit = await _create_product(
        client, token, "A" * SRI_DESCRIPTION_MAX_LENGTH, key="product-at-sri-limit"
    )
    assert at_limit.status_code == 201, at_limit.text

    over_limit = await _create_product(
        client, token, "A" * (SRI_DESCRIPTION_MAX_LENGTH + 1), key="product-over-sri-limit"
    )
    assert over_limit.status_code == 422, over_limit.text
    assert over_limit.json()["detail"][0]["loc"][-1] == "name"
