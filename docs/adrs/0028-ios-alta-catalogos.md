# ADR 0028 · Alta de clientes y productos desde una factura en iOS

El 19 de noviembre de 2026 Carlos autorizó publicar ambas altas después de la revisión de negocio, UI/UX, QA y CI.

La app consulta el RUC o la cédula en la empresa activa antes de crear un cliente. Para productos consulta el código exacto. Una coincidencia activa permite seleccionar el registro. Un registro inactivo, un proveedor con la misma identificación o cualquier otra colisión requiere resolver el conflicto en el catálogo. El formulario muestra el nombre de la empresa y devuelve el registro confirmado al borrador abierto.

El servidor obtiene la empresa y el usuario de la sesión autenticada. Los roles owner, admin y billing necesitan los permisos específicos de alta y lectura del catálogo. Las rutas llaman a los mismos servicios de maestros que la web. La API vuelve a comprobar la membresía antes de insertar, audita la operación y conserva su clave de idempotencia. El precio admite seis decimales. La categoría fiscal debe pertenecer a la empresa y estar vigente en la fecha fiscal.

El cliente público de producción recibe sólo los permisos nuevos de alta. Para el ensayo fiscal BTOB-SAS se copia el cliente y el servicio elegido a un entorno privado de pruebas. El precio especial aplica a la línea de USD 0,05. El producto conserva su precio de catálogo. El RIDE y el XML proceden de los servicios de la web en modo simulador. El correo termina en el buzón de captura del ensayo.

[Política de conexión iOS](0024-ios-production-connection-policy.md) · [Emisión de prueba](0027-ios-test-invoice-delivery.md)
