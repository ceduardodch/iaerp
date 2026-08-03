"""Texto por defecto de la plantilla de cobranza.

Vive en ``core`` (módulo hoja, sin dependencias de la app) porque lo necesitan
tanto ``models/receivables.py`` (default de la columna) como
``schemas/receivables.py`` (default del payload). Ponerlo en cualquiera de los
dos obligaría a que uno importe al otro y a torcer el orden de capas.
"""

from __future__ import annotations

# Cuerpo sugerido del correo de cobranza. Cada tenant lo edita en Configuración
# (``CollectionPolicy.email_body``); este es solo el punto de partida.
#
# Prioriza el acuerdo de pago sobre el reclamo: un cliente que no puede pagar
# todo responde mucho más a "dinos en qué plazo puedes" que a un aviso de mora,
# y así la conversación entra por el correo en vez de perderse. Los datos
# bancarios NO se escriben aquí: van en ``payment_instructions`` (por tenant) y
# el renderizador los agrega al pie, para que una plantilla compartida jamás
# filtre la cuenta de otra empresa.
DEFAULT_COLLECTION_EMAIL_BODY = (
    "Estimado/a {{cliente}},\n\n"
    "Le escribimos de {{empresa}} para recordarle que mantiene un saldo pendiente "
    "de {{saldo}}, con vencimiento el {{vencimiento}}.\n\n"
    "Si ya realizó el pago, respóndanos con el comprobante y lo conciliamos de inmediato.\n\n"
    "Si en este momento no le es posible cubrirlo por completo, podemos acordar un "
    "plan de pagos: respóndanos indicando qué monto y qué fechas le funcionan y "
    "coordinamos un cronograma.\n\n"
    "Al pie encontrará el detalle del saldo y nuestros datos bancarios para la "
    "transferencia.\n\n"
    "Gracias por su atención,\n"
    "{{empresa}}"
)

__all__ = ["DEFAULT_COLLECTION_EMAIL_BODY"]
