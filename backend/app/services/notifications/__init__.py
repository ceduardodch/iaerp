"""Avisos internos: cuando avisar, que decir y a quien.

Modulos del paquete:

- ``catalog.py``: valores por defecto de cada tipo de aviso (todo apagado).
- ``scheduling.py``: aritmetica de calendario, pura y sin base de datos.
- ``planner.py``: crea los ``NotificationEvent`` que corresponden a hoy.
- ``delivery.py``: resuelve destinatarios, renderiza y entrega.
- ``channels.py``: que proveedor envia y con que remitente sale cada tenant.
- ``webhooks.py``: rebotes y quejas que reporta el proveedor.

El envio en si vive en ``integrations/notifications/`` (``email_sender.py`` con
el contrato y el stub, ``brevo.py`` con el cliente real), para que cambiar de
proveedor no arrastre reglas de negocio.
"""

from app.services.notifications import (
    catalog,
    channels,
    delivery,
    planner,
    scheduling,
    webhooks,
)

__all__ = ["catalog", "channels", "delivery", "planner", "scheduling", "webhooks"]
