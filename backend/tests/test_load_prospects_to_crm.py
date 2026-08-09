import importlib.util
from collections import Counter
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "load_prospects_to_crm.py"
spec = importlib.util.spec_from_file_location("load_prospects_to_crm", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
prospects = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prospects)


async def test_service_account_token_renews_after_unauthorized_response() -> None:
    issued_tokens = ["first-token", "renewed-token"]
    authorizations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(prospects.TOKEN_ENDPOINT):
            return httpx.Response(
                200,
                json={"access_token": issued_tokens.pop(0), "expires_in": 300},
            )
        authorizations.append(request.headers["Authorization"])
        if len(authorizations) == 1:
            return httpx.Response(401)
        return httpx.Response(200, json=[])

    token = prospects.ServiceAccountToken("client-id", "client-secret")
    async with httpx.AsyncClient(
        base_url="https://iaerp.b2b.com.ec",
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await token.request(
            client,
            "GET",
            "/api/v1/crm/leads",
            headers={"Idempotency-Key": "prospect-test-key"},
        )

    assert response.status_code == 200
    assert authorizations == ["Bearer first-token", "Bearer renewed-token"]


def _csv(tmp_path, cabecera: str, *filas: str):
    ruta = tmp_path / "lista.csv"
    ruta.write_text("\n".join([cabecera, *filas]) + "\n", encoding="utf-8-sig")
    return str(ruta)


CABECERA_VIEJA = "contactar,empresa,correo,telefono,empleados,provincia,ruc,ciiu,nota"


def test_hand_written_note_does_not_flag_a_prospect_as_competition(tmp_path) -> None:
    """El CSV se edita a mano; una anotación cualquiera no es un marcador.

    Antes bastaba con que la nota no estuviera vacía, así que escribir
    "no contesta" convertía al prospecto en sospechoso de competencia y le
    inyectaba la advertencia de AWS Partner Finder en el lead.
    """
    ruta = _csv(
        tmp_path,
        CABECERA_VIEJA,
        "2026-08-10,ACME,a@acme.ec,022345678,40,PICHINCHA,1790000000001,J6202,no contesta",
        "2026-08-10,BIGCO,b@bigco.ec,022345679,900,PICHINCHA,1790000000002,J6202,"
        + prospects.NOTA_COMPETENCIA,
    )
    acme, bigco = prospects.targets_from_csv(ruta)
    assert acme["prioridad"] == 1
    assert bigco["prioridad"] == 3


def test_explicit_priority_column_wins_over_the_note(tmp_path) -> None:
    ruta = _csv(
        tmp_path,
        "contactar,empresa,correo,telefono,empleados,provincia,ruc,ciiu,segmento,prioridad,nota",
        "2026-08-10,ACME,a@acme.ec,022345678,40,PICHINCHA,1790000000001,J6202,isv,3,lo que sea",
    )
    assert prospects.targets_from_csv(ruta)[0]["prioridad"] == 3


def test_csv_without_segment_column_refuses_to_guess(tmp_path) -> None:
    """Cargar `educacion.csv` sin decirlo escribía el guion de AWS a universidades."""
    ruta = _csv(
        tmp_path,
        CABECERA_VIEJA,
        "2026-08-10,UNIVERSIDAD X,rector@u.edu.ec,022345678,300,PICHINCHA,1790000000003,P8530,",
    )
    targets = prospects.targets_from_csv(ruta)
    with pytest.raises(SystemExit):
        prospects.segment_from_csv(targets, None)
    assert prospects.segment_from_csv(targets, "educacion") == "educacion"


def test_segment_declared_in_the_csv_must_match_the_flag(tmp_path) -> None:
    ruta = _csv(
        tmp_path,
        "contactar,empresa,correo,telefono,empleados,provincia,ruc,ciiu,segmento,prioridad,nota",
        "2026-08-10,UNIVERSIDAD X,r@u.edu.ec,02234,300,PICHINCHA,1790000000003,P8530,educacion,1,",
    )
    targets = prospects.targets_from_csv(ruta)
    assert prospects.segment_from_csv(targets, None) == "educacion"
    with pytest.raises(SystemExit):
        prospects.segment_from_csv(targets, "isv")


def test_schedule_honours_the_date_planned_in_the_csv(tmp_path) -> None:
    """Recalcular desde mañana descartaba en silencio el orden editado a mano."""
    ruta = _csv(
        tmp_path,
        CABECERA_VIEJA,
        "2026-09-15,ACME,a@acme.ec,022345678,40,PICHINCHA,1790000000001,J6202,",
    )
    fechas = prospects.assign_schedule(prospects.targets_from_csv(ruta))
    assert fechas[0].date().isoformat() == "2026-09-15"


def test_schedule_without_dates_keeps_three_contacts_per_business_day() -> None:
    fechas = prospects.assign_schedule([{"ruc": str(i)} for i in range(7)])
    por_dia = Counter(fecha.date() for fecha in fechas)
    assert sorted(por_dia.values(), reverse=True) == [3, 3, 1]
    assert all(fecha.weekday() < 5 for fecha in fechas)


async def test_existing_rucs_walks_every_page() -> None:
    """Con una sola petición la deduplicación se detenía en 100 leads."""
    tamanio = prospects.LEADS_PAGE_SIZE
    primera = [
        {"party": {"identificationNumber": f"ruc-{i}"}} for i in range(tamanio)
    ]
    segunda = [{"party": {"identificationNumber": "ruc-ultimo"}}]
    paginas = [primera, segunda]
    pedidos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(prospects.TOKEN_ENDPOINT):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        pedidos.append(str(request.url))
        return httpx.Response(200, json=paginas.pop(0) if paginas else [])

    token = prospects.ServiceAccountToken("client-id", "client-secret")
    async with httpx.AsyncClient(
        base_url="https://iaerp.b2b.com.ec",
        transport=httpx.MockTransport(handler),
    ) as client:
        rucs = await prospects.existing_rucs(client, token)

    assert len(pedidos) == 2
    assert f"offset={tamanio}" in pedidos[1]
    assert "ruc-ultimo" in rucs
    assert len(rucs) == tamanio + 1
