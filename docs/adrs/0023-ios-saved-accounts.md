# ADR 0023: Cuentas guardadas y desbloqueo local en iPhone

- Estado: Accepted
- Fecha: 2026-11-18
- Solicitud humana: Carlos pide guardar varios usuarios y elegir uno para entrar
  sin escribir claves cada vez. Autoriza este incremento local; no acceso a
  producción, distribución ni emisión SRI.
- Amplía ADR 0022 en identidad local; conserva sus límites de datos de negocio.

## Decisión

Guardar varias sesiones OIDC dentro de una colección cifrada de Keychain,
`WhenUnlockedThisDeviceOnly`, sin sincronización. Nunca guardar contraseñas.
Cada registro tiene un UUID estable y liga configuración completa, issuer,
cliente, subject y organización. Dos usuarios de la misma empresa son dos
perfiles; un nombre visible no identifica ni autoriza una cuenta.

Mostrar nombre, usuario OIDC y empresa. Si un perfil antiguo no incluye usuario,
mostrar su identificador estable como alternativa. Distinguir proveedores cuando
hay más de uno. El alta abre AppAuth en navegador efímero con `prompt=login`;
el usuario se identifica allí. Repetir un alta sólo actualiza el mismo perfil
si coinciden identidad, organización y configuración completas.

Cada selección requiere una evaluación nueva de `deviceOwnerAuthentication`:
Face ID o código del dispositivo. Es una comprobación del usuario del iPhone,
no prueba de quién es el titular ERP. Sin política disponible, con cancelación
o resultado tardío, no restaurar ni refrescar la credencial. Declarar el motivo
de Face ID en Info.plist. No crear una opción para saltar este control.

Después del desbloqueo, restaurar sólo el UUID elegido, validar metadata OIDC,
renovar si corresponde y consultar `/context`. El servidor sigue validando
firma, membresía, tenant y permisos; Face ID no sustituye esas reglas. Una sesión
revocada o identidad inválida requiere iniciar sesión otra vez. Fallos de red
transitorios bloquean la memoria y conservan el perfil para reintentar.

Sólo hay una sesión activa. Cambiar cuenta, cancelar un acceso, probar demo o
pasar realmente a segundo plano invalida operaciones y borra el contexto en
memoria; mantiene las cuentas guardadas. El cambio elimina documentos temporales
antes de abrir otro contexto. La inactividad breve de Face ID o del navegador
no dispara otro bloqueo; el escudo opaco sigue cubriendo todas las ventanas.

**Cambiar cuenta** conserva sesiones. **Cerrar sesión** quita la activa e intenta
revocación/cierre remoto, informando fallos. **Quitar de este iPhone** elimina
sólo el registro elegido con confirmación identificada; no promete cerrar otros
dispositivos ni borrar cookies del proveedor. Ninguna operación borra las otras
cuentas por error. Un proveedor puede invalidar otras sesiones propias: cada
restauración vuelve a consultar al servidor.

La migración del registro único v1 escribe primero la colección v2. Incluso una
colección vacía es autoritativa para impedir que reaparezca un registro antiguo
tras una interrupción. Un fallo se informa sin borrar otras cuentas. Los
refrescos tardíos quedan ligados a UUID y generación y no reinsertan perfiles
olvidados ni reemplazan otra cuenta.

## Validación y límites

Probar dos usuarios de la misma empresa y nombre, dos empresas/proveedores,
A → B → A, refresco tardío, fallos de migración, borrado individual, cancelación
de desbloqueo, bloqueo durante un prompt y conservación de perfiles al cambiar
o usar demo. Revisar selector/confirmación con VoiceOver y texto máximo.
Los fixtures visuales existen sólo en Debug del simulador y no sustituyen el
desbloqueador real. No se compilan para iPhone ni distribución.

No añade caché de negocio, escrituras offline o registro durable de borradores.
Los P1 previos de permisos efectivos por tenant y recuperación tras terminación
siguen bloqueando el piloto de escritura. Cliente Keycloak real deshabilitado.
La firma, instalación y prueba Face ID en el iPhone siguen siendo cierres físicos.

Fuentes: [Apple LocalAuthentication](https://developer.apple.com/documentation/localauthentication/lacontext),
[política del dispositivo](https://developer.apple.com/documentation/localauthentication/lapolicy/deviceownerauthentication),
[OIDC, solicitud de autenticación](https://openid.net/specs/openid-connect-core-1_0.html#AuthRequest).
