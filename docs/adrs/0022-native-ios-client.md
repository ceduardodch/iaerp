# ADR 0022: Cliente nativo iOS por entregas

- Estado: Accepted
- Fecha: 2026-11-17
- Aprobación humana: Carlos indicó «Empecemos» tras recibir el backlog y la
  propuesta SwiftUI. Se acepta la dirección y el primer incremento local;
  no autoriza acceso productivo, emisión real, push o distribución.
- Alcance: cliente iPhone; no sustituye los ADR de dominio, identidad o plataforma.

## Contexto

Carlos solicita IAERP instalable en su iPhone 14 actualizado, con tecnología
iOS actual y desarrollo por partes. Prioriza crear facturas y consultar clientes.
`docs/04-architecture.md` excluye el cliente nativo del
MVP original. Esta decisión amplía el alcance con entregas móviles pequeñas,
sin cambiar las reglas del backend ni el alcance histórico del MVP web.

El [ADR 0023](0023-ios-saved-accounts.md) amplía las identidades locales.
El [ADR 0024](0024-ios-production-connection-policy.md) define la conexión
productiva y permisos nativos. El [ADR 0025](0025-ios-durable-draft-recovery.md)
sustituye sólo la exclusión de persistencia para un guardado pendiente mínimo;
catálogo offline y emisión fiscal conservan sus puertas.

## Decisión

1. Crear un cliente Swift/SwiftUI en `ios/IAERP`, con el SDK estable compatible
   más reciente y mínimo iOS pendiente de confirmar con el teléfono del usuario.
2. Consumir REST de IAERP. Backend conserva cálculos fiscales, permisos,
   tenancy, idempotencia, auditoría, firma, reconciliación SRI y trabajos asíncronos.
   REST, MCP y workers mantienen los mismos casos de uso.
3. Definir cliente Keycloak público iOS propio, Authorization Code + PKCE S256,
   navegador de autenticación del sistema, callbacks exactos, state/nonce y
   validación OIDC con librería mantenida evaluada en PoC. Sin secreto embebido,
   tokens técnicos, claves del SRI ni certificados de firma en la app.
4. Respetar ADR 0009: un token representa una organización y backend valida
   membresía activa. Cambiar empresa requiere autorización nueva, cancelación
   de lecturas y limpieza de estado/archivos previos. No confiar en tenant del cliente.
5. Proteger tokens en Keychain. Empezar sin datos de negocio persistentes ni
   escrituras offline: sesión API efímera, caché de disco deshabilitada y sin
   cookies propias. Documentos temporales tienen protección y limpieza;
   compartir requiere acción humana. Ocultar el snapshot al pasar a segundo
   plano desde el primer acceso a datos. Logout limpia sesión local/Keychain,
   intenta revocar refresh/cerrar sesión OIDC e informa fallos sin prometer
   borrar las cookies del navegador. Caché persistente requiere otra decisión.
6. Usar Decimal exacto en modelos Swift y fechas fiscales de Guayaquil. La app
   muestra resultados del backend; no copia reglas fiscales ni suma listas incompletas.
7. Adaptar `docs/12-frontend-design-system.md` a componentes SwiftUI compartidos,
   conservando nombres y jerarquía de acciones. Antes de pantallas, aprobar y
   documentar equivalencias nativas; no duplicar React dentro de un contenedor web.
8. Entregar instalación sintética, acceso/clientes, borrador/emisión sandbox y
   luego consultas documentales y módulos elegidos. Cada parte tiene pruebas y
   revisión humana. La primera meta no exige
   paridad con toda la web ni publicación en App Store.
9. Validar con Swift Testing, XCUITest y CI macOS. Firma/distribución iOS serán
   un flujo separado, con autorización para subir a TestFlight/App Store.
   No cambiar el flujo `release → PR → main` ni el despliegue backend por Coolify.

## Concreción del primer cliente

Carlos autoriza el 2026-11-17 continuar Partes 1–3 mientras difiere conectar el
teléfono unas dos horas. Esa dependencia física no impide preparar el resto en
simulador. Se elige AppAuth iOS 3.0.0 fijado por revisión en SwiftPM; se mantiene
SwiftUI y no se añaden frameworks de interfaz o persistencia de negocio.

La configuración pública y allowlist de archivos se guardan dentro del perfil
protegido de Keychain con los tokens. Continuar sesión exige acción explícita,
coincidencia completa del perfil, validación OIDC y nueva consulta `/context`.
Metadata JWT local es un filtro, no sustituye la firma/membresía del backend.

Los documentos usan sesión de descarga sin Bearer ni cookies para URLs HTTPS
prefirmadas del origen API o allowlist explícita, límite de 20 MiB y SHA256.
Archivos protegidos/excluidos de backup se purgan desde una raíz privada estable
al iniciar, salir o cambiar de empresa, incluyendo restos de un cierre inesperado.

La app expone sólo guardar borrador como escritura. La emisión SRI sandbox
(IOS-011), la integración Keycloak/API real y la instalación física siguen
siendo cierres propios; ningún resultado sintético los acredita.

La revisión del realm y del backend versionados encontró que `invoices:write`
no se restringe por los roles de la membresía. La plantilla del cliente queda
deshabilitada: activar el piloto exige una política por tenant y pruebas con
el mismo usuario facturador en una empresa y consulta en otra, además de
revocación y POST directo denegado. Esta decisión no modifica los permisos del
backend ni afirma el estado del realm desplegado.

El guardado incierto conserva clave/payload en memoria y se probó dentro del
mismo proceso. Antes de escrituras reales falta recuperarlos tras terminación
de iOS, ligados a usuario/tenant/perfil y con reconciliación del resultado.
El registro durable exige otra decisión explícita porque esta versión excluye
persistencia de negocio; no se añade de forma tácita ni se habilita el cliente
real mientras esa puerta y los permisos sigan abiertos.

## Alternativas consideradas

| Alternativa | Evaluación |
| --- | --- |
| Web responsive/PWA | Reutiliza más interfaz y sigue siendo válida para navegador. No es la elección propuesta para un cliente nativo instalable con integración iOS. |
| React Native/Expo | Puede convenir si se prioriza Android también. Hoy el pedido es iPhone; añade una capa que no reutiliza directamente los componentes React DOM de IAERP. |
| SwiftUI | Propuesta por acceso directo a navegación, accesibilidad y APIs Apple. Requiere interfaz propia, Xcode, firma y pruebas en dispositivo. |

## Consecuencias y pendientes

- Aumenta la superficie de cliente y el coste de mantenimiento de interfaz y CI.
- No requiere por defecto una base o backend móvil aparte. Brechas de API se
  justifican y revisan antes de añadir endpoints.
- Una cuenta gratuita puede servir para instalación inicial con firma temporal;
  TestFlight requiere membresía de pago y renovación de builds. Ver fuentes en backlog.
- Confirmados iPhone 14 actualizado y prioridad de facturas/clientes. Falta
  versión exacta iOS, cuenta, mínimo soportado y validación de autenticación
  móvil. Demo compilada y abierta en simulador iPhone 14/iOS 26.5 con Xcode 27.2;
  cinco unitarias/ocho casos y tres pruebas UI correctas, incluida accesibilidad
  de listado/ficha con texto máximo. Firma e instalación física pendientes:
  Carlos conectará el teléfono después. Sin cliente productivo configurado.
- Dirección/alcance aceptados tras revisión del plan y la indicación humana
  «Empecemos». Permite app sintética y PoC local en entorno de pruebas. Antes de
  habilitar acceso autenticado al piloto: Backend Platform, MCP AI Security y QA
  revisan el PoC; escrituras fiscales incluyen SRI. No exigir PoC terminado como
  condición previa para poder escribir ese mismo PoC.
- Alcance, arquitectura, roadmap, sistema visual y calidad enlazan la ampliación.
  La exclusión original del MVP no se borra como si la app móvil hubiese sido
  parte del alcance histórico.

## Trazabilidad

[Backlog iOS con entregas, criterios y fuentes](../backlog/ios-backlog.md).
