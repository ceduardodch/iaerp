# Conectar Gmail (Google Workspace) — Guía de configuración

La integración de Gmail **ya está construida** en IAERP (botón *Conectar Google
Workspace* en **Empresa → Google Workspace**). Solo falta registrar **una** app
OAuth en Google —lo hace el operador de IAERP una sola vez— y poner 3 variables
de entorno. Después, **cada tenant** conecta su propio correo con un botón.

> **Concepto clave:** el `client_id`/`client_secret` es la identidad de **la app
> IAERP** ante Google (uno solo, tuyo como operador), NO de cada cliente. Cada
> cliente autoriza su cuenta y sus **tokens** se guardan cifrados por `tenant_id`.
> Así funcionan Claude, ChatGPT, Slack, etc.

---

## Parte A — Crear la app OAuth en Google (una sola vez)

1. Entra a **Google Cloud Console** → https://console.cloud.google.com/
2. **Crea o elige un proyecto** (arriba a la izquierda). Ej: "IAERP".
3. **Habilita la Gmail API:**
   *APIs y servicios → Biblioteca* → busca **Gmail API** → **Habilitar**.
4. **Configura la pantalla de consentimiento OAuth**
   (*APIs y servicios → Pantalla de consentimiento de OAuth*):
   - Tipo de usuario: **Externo**.
   - Nombre de la app, correo de soporte y de contacto del desarrollador.
   - **Scopes:** agrega
     - `.../auth/gmail.readonly`
     - `.../auth/gmail.send`
     - (`openid`, `email`, `profile` suelen estar por defecto)
   - **Usuarios de prueba:** agrega tu(s) correo(s). En modo prueba **solo estos
     correos** podrán conectar (ver Parte D para abrirlo a todos).
5. **Crea las credenciales**
   (*APIs y servicios → Credenciales → Crear credenciales → ID de cliente de
   OAuth*):
   - Tipo de aplicación: **Aplicación web**.
   - **URIs de redirección autorizados** → agrega EXACTAMENTE la URL del callback
     de tu despliegue:
     ```
     https://TU-DOMINIO/api/v1/crm/integrations/google/callback
     ```
     (para pruebas locales, además:
     `http://localhost:8000/api/v1/crm/integrations/google/callback`)
   - Crear → copia el **Client ID** y el **Client Secret**.

> ⚠️ El **redirect URI** debe coincidir **carácter por carácter** con la variable
> `GOOGLE_OAUTH_REDIRECT_URI` (Parte B). Si no, Google rechaza con
> `redirect_uri_mismatch`.

---

## Parte B — Poner las 3 variables de entorno (en Coolify)

En el servicio del **backend** (API), agrega:

```
GOOGLE_CLIENT_ID=<el Client ID de la Parte A>
GOOGLE_CLIENT_SECRET=<el Client Secret de la Parte A>
GOOGLE_OAUTH_REDIRECT_URI=https://TU-DOMINIO/api/v1/crm/integrations/google/callback
```

Reinicia el backend. El endpoint `GET /crm/integrations` empezará a devolver
`googleConfigurationAvailable: true`, y en la UI el botón **se habilita**.

> El `client_secret` es una credencial: ponlo solo en el gestor de variables de
> entorno del servidor, nunca en el frontend ni en el repo.

---

## Parte C — Probar el flujo (por cada cliente/tenant)

1. En IAERP, ve a **Empresa → Google Workspace**.
2. Pulsa **Conectar Google Workspace**. Te redirige a Google.
3. Elige la cuenta y **Autorizar**. Google vuelve al callback de IAERP.
4. El backend intercambia el código por tokens (con `refresh_token`, porque el
   flujo pide `access_type=offline`), los **cifra** y los guarda con el
   `tenant_id` de ese cliente.
5. El panel pasa a **Conectado** y muestra el correo. Ya puedes enviar correos y
   sincronizar el inbox del CRM (`POST /crm/gmail/sync/now`).

Repetir con otro tenant conecta **otra** cuenta, aislada por `tenant_id`. Un solo
`client_id` de app da servicio a todos.

---

## Parte D — Abrirlo a clientes externos (cuando salgas de pruebas)

Los scopes `gmail.readonly` y `gmail.send` son **restringidos** por Google.
Mientras la app esté en **modo prueba**, solo los *usuarios de prueba* pueden
conectar. Para que **cualquier** cliente conecte sin que lo agregues a mano:

1. En la **pantalla de consentimiento**, pasa el estado a **En producción**
   (*Publicar app*).
2. Google pedirá **verificación de la app** (dominio, logo, política de
   privacidad) y, por usar scopes restringidos de Gmail, una **evaluación de
   seguridad anual (CASA)** con un tercero autorizado.
3. Hasta completar la verificación, los usuarios verán la pantalla de "app no
   verificada" (pueden continuar bajo su riesgo) o el límite de 100 usuarios.

Esto es trámite con Google (no requiere cambios de código) y aplica a cualquier
app multi-tenant que lea/envíe Gmail.

---

## Referencia técnica

| Elemento | Valor |
|----------|-------|
| Scopes | `openid email profile gmail.readonly gmail.send` |
| Redirect URI | `https://TU-DOMINIO/api/v1/crm/integrations/google/callback` |
| Vars backend | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` |
| Estado por tenant | tabla `GmailIntegration` (tokens cifrados, filtrada por `tenant_id`) |
| Endpoints | `GET /crm/integrations`, `POST /crm/integrations/google/authorize`, `GET /crm/integrations/google/callback`, `DELETE /crm/integrations/google`, `POST /crm/gmail/sync/now` |

Errores comunes:
- **`redirect_uri_mismatch`**: la URI en Google ≠ `GOOGLE_OAUTH_REDIRECT_URI`.
- **Botón deshabilitado / "Faltan GOOGLE_CLIENT_ID…"**: variables no cargadas o
  backend sin reiniciar.
- **`Google OAuth is not configured` (503)**: falta alguna de las 3 variables.
