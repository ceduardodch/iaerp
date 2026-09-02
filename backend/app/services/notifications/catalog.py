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
# ``services/collection_email.py``.
PLACEHOLDERS = (
    "{{empresa}}",
    "{{periodo}}",
    "{{fecha_limite}}",
    "{{dias_restantes}}",
    "{{estado}}",
    "{{pendientes}}",
    "{{aviso_feriados}}",
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


DEFINITIONS: dict[str, RuleDefinition] = {
    IVA_DECLARACION.rule_type: IVA_DECLARACION,
}

# Tipos que el planificador sabe calcular hoy.
IMPLEMENTED_RULE_TYPES = tuple(DEFINITIONS)


def definition_for(rule_type: str) -> RuleDefinition:
    return DEFINITIONS[rule_type]


__all__ = [
    "DEFINITIONS",
    "IMPLEMENTED_RULE_TYPES",
    "IVA_DECLARACION",
    "PLACEHOLDERS",
    "RuleDefinition",
    "definition_for",
]
