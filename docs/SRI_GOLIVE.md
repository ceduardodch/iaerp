# Go-live SRI — activar transmisión real (pruebas → producción)

Guía para pasar de la facturación simulada a la **transmisión real** contra los
web services del SRI de Ecuador.

> ⚠️ Antes de esto, con `SRI_TRANSMISSION_MODE=simulator` las autorizaciones son
> **fingidas** por el simulador y **NO tienen validez legal**. La transmisión real
> requiere los pasos de abajo + certificar en el ambiente de pruebas del SRI.

## Qué se implementó

`app/integrations/sri/soap.py` — `SoapSRIClient`, cliente SOAP real que cumple el
mismo contrato `SRIClient` que usa el worker de transmisión:
- **Recepción** (`RecepcionComprobantesOffline` → `validarComprobante`): envía el
  XML firmado en base64 → `RECIBIDA` (RECEIVED) / `DEVUELTA` (RETURNED).
- **Autorización** (`AutorizacionComprobantesOffline` → `autorizacionComprobante`):
  consulta por clave de acceso → `AUTORIZADO` / `NO AUTORIZADO` / `EN PROCESO`.
- Selección de ambiente: `"1"` pruebas (`celcer.sri.gob.ec`), `"2"` producción
  (`cel.sri.gob.ec`).

El worker (`workers/sri_transmission.py`) elige simulador o SOAP según config, y
mantiene igual la lógica de reintentos y reconciliación.

## Paso 1 — Certificado de firma (.p12)

La firma XAdES-BES ya está implementada (`app/services/signing.py`). Solo falta
que tu certificado esté disponible para el backend (variables de entorno):

```
IAERP_SIGNING_CERT_PATH=/ruta/segura/tu-certificado.p12
IAERP_SIGNING_CERT_PASSWORD=********
```

> El `.p12` y su contraseña son tu firma legal: van solo en el gestor de
> variables/secretos del servidor, nunca en el repo ni en el frontend.

## Paso 2 — Activar transmisión SOAP en ambiente de PRUEBAS

Variables de entorno del backend:

```
SRI_TRANSMISSION_MODE=soap
SRI_ENVIRONMENT=1        # 1 = pruebas (celcer)
# opcional: SRI_HTTP_TIMEOUT=30
```

Y en la app, el **ambiente fiscal del tenant** debe ser también `1` (Empresa →
ajustes fiscales), para que el `ambiente` del XML coincida con el endpoint. Si no
coinciden, el SRI devuelve el comprobante.

Reinicia el backend. A partir de aquí, emitir una factura la transmite **de
verdad** al ambiente de pruebas del SRI.

## Paso 3 — Certificar contra el SRI (esto se corre en tu despliegue)

1. Emite un juego de comprobantes de prueba (factura, nota de crédito) desde la
   app con datos válidos.
2. Verifica en el detalle que el estado llegue a **AUTORIZADO** con un
   `numeroAutorizacion` real del SRI (no simulado) y que el XML autorizado y el
   RIDE se generen.
3. Prueba también casos negativos (RUC mal, secuencial repetido) y confirma que
   el sistema refleje `DEVUELTA` / `NO AUTORIZADO` con los mensajes del SRI.

> Esta certificación **no se puede hacer desde el repo/CI**: requiere el `.p12`
> real y acceso de red a `celcer.sri.gob.ec`. Se corre en el servidor.

## Paso 4 — Pasar a PRODUCCIÓN

Solo cuando pruebas esté validado:

```
SRI_ENVIRONMENT=2        # 2 = producción (cel.sri.gob.ec)
```

Y el ambiente fiscal del tenant a `2`. Reinicia. Las primeras facturas reales
conviene monitorearlas de cerca.

## Referencia técnica

| Variable | Valores | Qué hace |
|----------|---------|----------|
| `SRI_TRANSMISSION_MODE` | `simulator` \| `soap` | Simulado (dev) o real |
| `SRI_ENVIRONMENT` | `1` \| `2` | Pruebas (celcer) / Producción (cel) |
| `SRI_HTTP_TIMEOUT` | segundos (30) | Timeout de cada llamada SOAP |
| `SRI_RECEPTION_URL` / `SRI_AUTHORIZATION_URL` | URL | Override opcional (pruebas/mocks) |
| `IAERP_SIGNING_CERT_PATH` / `IAERP_SIGNING_CERT_PASSWORD` | — | Certificado .p12 y clave |

Endpoints oficiales usados:
- Pruebas: `https://celcer.sri.gob.ec/comprobantes-electronicos-ws/{Recepcion,Autorizacion}ComprobantesOffline`
- Producción: `https://cel.sri.gob.ec/comprobantes-electronicos-ws/{Recepcion,Autorizacion}ComprobantesOffline`

Mapeo de estados: `RECIBIDA→RECEIVED`, `DEVUELTA→RETURNED`, `AUTORIZADO→AUTHORIZED`,
`NO AUTORIZADO→NOT_AUTHORIZED`, `EN PROCESO/sin autorizaciones→PENDING_AUTHORIZATION`.
