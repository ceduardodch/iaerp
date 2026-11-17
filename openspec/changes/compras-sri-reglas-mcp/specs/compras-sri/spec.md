## ADDED Requirements

### Requirement: Diagnóstico del acceso SRI
El importador SHALL distinguir acceso guardado, sesión validada y errores del SRI sin mostrar la clave.

#### Scenario: Acceso asociado a otro RUC
- **WHEN** alguien intenta guardar un RUC distinto al de la empresa activa
- **THEN** IAERP rechaza el cambio antes de guardar la clave

#### Scenario: Verificar sin importar
- **WHEN** el operador ejecuta la comprobación para una empresa
- **THEN** el importador verifica el tenant y la apertura del módulo de recibidos sin descargar ni cargar comprobantes

#### Scenario: Consulta sin filas
- **WHEN** todos los tipos consultados del mes terminan sin filas
- **THEN** el importador informa cero comprobantes sin crear evidencias vacías

#### Scenario: CAPTCHA durante la prueba de descarga
- **WHEN** el SRI pide un CAPTCHA y el operador eligió continuar de forma manual
- **THEN** el importador conserva la sesión hasta que el operador resuelve el CAPTCHA y confirma la consulta
- **AND** en modo de prueba informa los conteos y valida el receptor sin importar los reportes

#### Scenario: Tarea diaria con perfiles separados
- **WHEN** el importador procesa todas las empresas en modo de sesión existente
- **THEN** reusa el perfil dedicado de cada empresa y avisa si el SRI pide iniciar sesión
- **AND** continúa con las empresas restantes

### Requirement: Importador administrado en b2b
El servidor b2b SHALL ejecutar el importador como servicio de Coolify a las 08:00 de Guayaquil con un navegador persistente por empresa.

#### Scenario: Recuperación después de reiniciar
- **WHEN** el servicio reinicia después de las 08:00 y queda una corrida pendiente o interrumpida
- **THEN** procesa el mes de ayer con los casos de uso e idempotencia existentes

#### Scenario: Intervención por CAPTCHA
- **WHEN** una consulta exige CAPTCHA
- **THEN** conserva la página y permite al operador resolverlo por el escritorio local del servidor
- **AND** consume el resultado de esa consulta antes de continuar
