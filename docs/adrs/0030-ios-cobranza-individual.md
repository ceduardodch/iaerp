# 0030 · Cobranza individual desde el iPhone

## Alcance

La app abre desde Inicio las cuentas pendientes de la empresa activa. Cada acción se refiere a una cuenta y una factura. El usuario revisa destinatario, saldo y vencimiento antes de confirmar un correo con la plantilla de la empresa.

## Decisiones

- El servidor verifica el saldo vigente, el permiso de la empresa y de la factura, la preferencia del cliente, el correo de destino y el último aviso. La confirmación del usuario queda asociada a una clave de solicitud. Los reintentos recuperan el resultado registrado.
- Una promesa de pago guarda la fecha acordada. El cobro conserva su vencimiento y su antigüedad. Los avisos se pausan hasta terminar el día prometido, según el calendario de Ecuador.
- Un cambio de vencimiento actualiza la cartera y el plan comercial de la cuota elegida. Cuando hay varias, se elige una cuota pendiente por fecha e importe. La app muestra el antes y el después y pide el motivo. El historial conserva el cambio. La factura autorizada, el XML y el RIDE se conservan.
- Los permisos de cobranza corresponden al titular, administración y cobranza de la empresa. Auditoría tiene lectura. La app usa permisos propios para notificar y para ajustar plazos. El correo queda limitado a la acción individual y la política general sigue bajo el control de la empresa.
- El envío se prueba con clientes sintéticos y un buzón de captura. La primera operación sobre una cuenta real la confirma el usuario en el teléfono.

[Backlog de producto](../backlog/ios-cobranza-benchmark.md)
