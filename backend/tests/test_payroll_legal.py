"""Reglas legales del rol de pagos ecuatoriano.

ESTE ARCHIVO NO SE MODIFICA para hacer pasar el codigo. Codifica lo que manda
la ley, no lo que hace la implementacion. Si una de estas pruebas falla, el
error esta en el calculo.

Cifras verificadas contra fuente oficial para 2026:

- SBU $482,00 -- Acuerdo Ministerial MDT-2025-195, vigente desde el 1-ene-2026.
- Aporte personal IESS 9,45% sobre la remuneracion imponible.
- Fondos de reserva 8,33%, solo desde el mes 13 de servicio.
- Decimo tercero: imponible / 12.  Decimo cuarto: SBU / 12.
- Los decimos y los fondos NO estan sujetos a aporte al IESS.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.payroll.calculations import calcular_rol
from app.services.payroll.parameters import SbuNoRegistrado, sbu_de

SUELDO = Decimal("1000.00")


def _empleado(**cambios):
    """Empleado de referencia: entro hace mas de un anio, todo mensualizado."""
    base = {
        "sueldo_mensual": SUELDO,
        "fecha_ingreso": date(2020, 1, 1),
        "fecha_salida": None,
        "decimo_tercero_mensualizado": True,
        "decimo_cuarto_mensualizado": True,
        "fondos_reserva_mensualizados": True,
    }
    return {**base, **cambios}


def test_sbu_2026_es_482() -> None:
    """Acuerdo Ministerial MDT-2025-195."""
    assert sbu_de(2026) == Decimal("482.00")
    assert sbu_de(2025) == Decimal("470.00")


def test_el_anio_en_curso_tiene_sbu_registrado() -> None:
    """El SBU se fija cada diciembre; olvidarlo rompe el rol de enero.

    Esta prueba existe para que el olvido se vea en CI y no en la nomina.
    """
    anio = date.today().year
    try:
        sbu_de(anio)
    except SbuNoRegistrado as exc:
        pytest.fail(str(exc))


def test_aporte_iess_es_945_por_ciento_del_sueldo() -> None:
    rol = calcular_rol(_empleado(), anio=2026, mes=6)
    assert rol.aporte_iess == Decimal("94.50")


def test_los_decimos_y_fondos_no_pagan_aporte_iess() -> None:
    """Error clasico: aportar sobre el total de ingresos.

    El aporte se calcula solo sobre la remuneracion imponible. Si se calculara
    sobre el total de ingresos, con este empleado daria mas de $110.
    """
    rol = calcular_rol(_empleado(), anio=2026, mes=6)
    assert rol.total_ingresos > rol.imponible
    assert rol.aporte_iess == (rol.imponible * Decimal("0.0945")).quantize(Decimal("0.01"))


def test_sin_un_anio_de_servicio_no_hay_fondos_de_reserva() -> None:
    """Codigo del Trabajo: se generan desde el mes 13."""
    recien = _empleado(fecha_ingreso=date(2026, 3, 1))
    assert calcular_rol(recien, anio=2026, mes=6).fondos_reserva == Decimal("0.00")


def test_al_mes_trece_aparecen_los_fondos_de_reserva() -> None:
    cumplido = _empleado(fecha_ingreso=date(2025, 6, 1))
    # Junio 2026 es el mes 13 de servicio.
    assert calcular_rol(cumplido, anio=2026, mes=6).fondos_reserva == Decimal("83.30")


def test_decimo_tercero_mensualizado_es_un_doceavo_del_imponible() -> None:
    rol = calcular_rol(_empleado(), anio=2026, mes=6)
    assert rol.decimo_tercero == Decimal("83.33")


def test_decimo_cuarto_mensualizado_es_un_doceavo_del_sbu() -> None:
    """No depende del sueldo: es el SBU, igual para todos."""
    rol = calcular_rol(_empleado(), anio=2026, mes=6)
    assert rol.decimo_cuarto == Decimal("40.17")
    caro = calcular_rol(_empleado(sueldo_mensual=Decimal("5000.00")), anio=2026, mes=6)
    assert caro.decimo_cuarto == rol.decimo_cuarto


def test_decimo_no_mensualizado_no_entra_al_rol_del_mes() -> None:
    """Se acumula y se paga en su fecha; no se reparte en el mes."""
    acumula = _empleado(
        decimo_tercero_mensualizado=False,
        decimo_cuarto_mensualizado=False,
    )
    rol = calcular_rol(acumula, anio=2026, mes=6)
    assert rol.decimo_tercero == Decimal("0.00")
    assert rol.decimo_cuarto == Decimal("0.00")


def test_quien_entra_a_mitad_de_mes_cobra_proporcional() -> None:
    """El mes comercial de nomina es de 30 dias."""
    rol = calcular_rol(
        _empleado(fecha_ingreso=date(2026, 6, 16)),
        anio=2026,
        mes=6,
    )
    # Del 16 al 30 son 15 dias de 30.
    assert rol.dias_trabajados == 15
    assert rol.imponible == Decimal("500.00")


def test_el_liquido_es_ingresos_menos_descuentos() -> None:
    rol = calcular_rol(_empleado(), anio=2026, mes=6)
    assert rol.total_ingresos == Decimal("1206.80")
    assert rol.total_descuentos == Decimal("94.50")
    assert rol.liquido == Decimal("1112.30")


def test_un_periodo_sin_sbu_registrado_falla_en_vez_de_adivinar() -> None:
    with pytest.raises(SbuNoRegistrado):
        calcular_rol(_empleado(), anio=1999, mes=6)
