"""Catalogo de avisos: valores por defecto de cada tipo de regla.

Separar el catalogo de la tabla ``notification_rules`` permite que un tenant
nuevo arranque con reglas sensatas sin que nadie las escriba, y que el usuario
las cambie despues sin tocar codigo.

**Todo nace apagado.** Un modulo que empieza mandando correos por su cuenta se
gana un filtro de spam el primer dia, y el usuario pierde la oportunidad de
revisar el contenido antes de que salga a su equipo.

``IMPLEMENTED_RULE_TYPES`` es lo que hoy sabe calcularse de verdad. El resto del
catalogo (``models/notifications.RULE_TYPES``) ya esta declarado en el esquema
pero no genera reglas todavia: crear filas para avisos que no hacen nada solo
confundiria a quien abra la pantalla de configuracion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Marcadores disponibles en las plantillas, mismo mecanismo que
# ``services/collection_email.py``. ``{{empresa}}`` sirve en todos; el resto
# depende del tipo de aviso (ver ``PLACEHOLDERS_BY_RULE_TYPE``).
PLACEHOLDERS = (
    "{{empresa}}",
    "{{periodo}}",
    "{{fecha_limite}}",
    "{{dias_restantes}}",
    "{{estado}}",
    "{{pendientes}}",
    "{{aviso_feriados}}",
    "{{cliente}}",
    "{{dia}}",
    "{{monto_referencia}}",
    "{{nota}}",
    "{{aporte_personal}}",
    "{{empleados}}",
    "{{aviso_patronal}}",
    "{{ingresos}}",
    "{{egresos}}",
    "{{resultado}}",
    "{{documentos}}",
    "{{iva_generado}}",
    "{{credito_tributario}}",
    "{{saldo}}",
    "{{aviso_preliminar}}",
)


@dataclass(frozen=True)
class RuleDefinition:
    """Valores por defecto de un tipo de aviso."""

    rule_type: str
    name: str
    schedule_kind: str
    offsets_days: str | None = None
    days_of_month: str | None = None
    send_hour: int = 8
    require_ack: bool = False
    audience_roles: list[str] = field(default_factory=list)
    subject: str = ""
    body: str = ""


IVA_DECLARACION = RuleDefinition(
    rule_type="IVA_DECLARACION",
    name="Recordatorio de declaracion de IVA",
    schedule_kind="OFFSET_TO_DUE",
    # Una semana antes para reaccionar, tres dias para cerrar evidencia, y el
    # dia anterior como ultimo aviso. El dia mismo no se incluye: si el aviso
    # llega el dia del vencimiento ya es tarde para conseguir un comprobante.
    offsets_days="-7,-3,-1",
    send_hour=8,
    require_ack=True,
    subject="Declaracion de IVA {{periodo}} vence el {{fecha_limite}}",
    body=(
        "La declaracion de IVA del periodo {{periodo}} de {{empresa}} vence el "
        "{{fecha_limite}} ({{dias_restantes}}).\n\n"
        "Estado del periodo: {{estado}}\n"
        "{{pendientes}}\n"
        "{{aviso_feriados}}\n"
        "IAERP no declara ni paga: este aviso es para que una persona lo haga."
    ),
)


CLIENTE_FACTURAR = RuleDefinition(
    rule_type="CLIENTE_FACTURAR",
    name="Recordatorio de facturacion a clientes",
    schedule_kind="DAY_OF_MONTH",
    # El dia lo pone cada calendario del cliente, no la regla; esta lista solo
    # agrega el recordatorio de seguimiento dos dias despues.
    offsets_days="0,2",
    send_hour=8,
    subject="Toca facturar a {{cliente}} ({{periodo}})",
    body=(
        "Segun su calendario, a {{cliente}} se le factura el dia {{dia}} de cada "
        "periodo. El periodo {{periodo}} todavia no tiene una factura emitida.\n\n"
        "{{monto_referencia}}\n"
        "{{nota}}\n"
        "IAERP no emite la factura: este aviso es para que una persona la haga."
    ),
)

IESS_APORTE = RuleDefinition(
    rule_type="IESS_APORTE",
    name="Recordatorio de aporte al IESS",
    schedule_kind="OFFSET_TO_DUE",
    offsets_days="-5,-2,-1",
    send_hour=8,
    require_ack=True,
    subject="Aporte al IESS de {{periodo}} vence el {{fecha_limite}}",
    body=(
        "El aporte al IESS del periodo {{periodo}} de {{empresa}} vence el "
        "{{fecha_limite}} ({{dias_restantes}}).\n\n"
        "Empleados en el rol: {{empleados}}\n"
        "Aporte personal retenido: {{aporte_personal}}\n"
        "{{aviso_patronal}}\n"
        "{{aviso_feriados}}\n"
        "IAERP no genera ni paga la planilla: este aviso es para que una "
        "persona lo haga."
    ),
)

RESUMEN_MENSUAL = RuleDefinition(
    rule_type="RESUMEN_MENSUAL",
    name="Resumen mensual de ingresos y egresos",
    schedule_kind="DAY_OF_MONTH",
    days_of_month="3,5",
    send_hour=8,
    subject="Resumen de {{periodo}}: {{resultado}}",
    body=(
        "Movimiento de {{empresa}} en {{periodo}}:\n\n"
        "Ingresos facturados: {{ingresos}}\n"
        "Egresos registrados: {{egresos}}\n"
        "Resultado: {{resultado}}\n\n"
        "{{documentos}}\n"
        "{{aviso_preliminar}}\n"
        "Son cifras operativas para mirar el mes, no una declaracion."
    ),
)

IVA_PREVIEW_MENSUAL = RuleDefinition(
    rule_type="IVA_PREVIEW_MENSUAL",
    name="Avance de IVA antes de cerrar el mes",
    schedule_kind="LAST_BUSINESS_DAY",
    # Al cierre del dia: la idea es ver como viene el mes con todo lo cargado.
    send_hour=17,
    subject="Avance de IVA {{periodo}} (preliminar)",
    body=(
        "Avance del IVA de {{empresa}} para {{periodo}}, con lo que hay "
        "cargado hoy:\n\n"
        "IVA generado en ventas: {{iva_generado}}\n"
        "Credito tributario en compras: {{credito_tributario}}\n"
        "Saldo estimado: {{saldo}}\n\n"
        "{{documentos}}\n"
        "{{aviso_preliminar}}\n"
        "Es un avance preliminar, no un valor declarable. La declaracion se "
        "prepara desde Tributario con la evidencia completa."
    ),
)


DEFINITIONS: dict[str, RuleDefinition] = {
    definition.rule_type: definition
    for definition in (
        IVA_DECLARACION,
        CLIENTE_FACTURAR,
        IESS_APORTE,
        RESUMEN_MENSUAL,
        IVA_PREVIEW_MENSUAL,
    )
}

# Tipos que el planificador sabe calcular hoy.
IMPLEMENTED_RULE_TYPES = tuple(DEFINITIONS)


def definition_for(rule_type: str) -> RuleDefinition:
    return DEFINITIONS[rule_type]


__all__ = [
    "CLIENTE_FACTURAR",
    "DEFINITIONS",
    "IESS_APORTE",
    "IMPLEMENTED_RULE_TYPES",
    "IVA_DECLARACION",
    "IVA_PREVIEW_MENSUAL",
    "PLACEHOLDERS",
    "RESUMEN_MENSUAL",
    "RuleDefinition",
    "definition_for",
]
