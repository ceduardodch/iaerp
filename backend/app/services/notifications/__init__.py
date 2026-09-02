"""Avisos internos: cuando avisar, que decir y a quien.

Modulos del paquete:

- ``catalog.py``: valores por defecto de cada tipo de aviso (todo apagado).
- ``scheduling.py``: aritmetica de calendario, pura y sin base de datos.
- ``planner.py``: crea los ``NotificationEvent`` que corresponden a hoy.
- ``delivery.py``: resuelve destinatarios, renderiza y entrega.

El envio en si vive en ``integrations/notifications/email_sender.py``, para que
cambiar de proveedor no arrastre reglas de negocio.
"""

from app.services.notifications import catalog, delivery, planner, scheduling

__all__ = ["catalog", "delivery", "planner", "scheduling"]
