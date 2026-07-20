# Graph Report - iaerp  (2026-07-20)

## Corpus Check
- 242 files · ~166,920 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2728 nodes · 5499 edges · 203 communities (170 shown, 33 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 933 edges (avg confidence: 0.72)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1bb297d9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- _setup_billing_masters
- App.tsx
- get_settings
- handle_invoice_authorized
- billing.py
- crm_integrations.py
- require_scopes
- FastAPI
- LineInput
- sign_xml
- build_invoice_xml
- crm.py
- APIModel
- server.py
- LeadsPage.tsx
- masters.py
- test_mcp_receivables.py
- receivables.py
- Party
- OutboxMessage
- Receivable
- test_access_key.py
- handle_invoice_signed
- test_receivables_aging.py
- AuthContext
- receivables.py
- Base
- Movement
- useKanban.ts
- initial_data.py
- SimulatorSRIClient
- compilerOptions
- SalesDocument
- build_ride_pdf
- get_store
- _create_authorized_invoice_stub
- compilerOptions
- devDependencies
- 🟢 Tareas COMPLETADAS (10) - SPRINT 1 COMPLETADO ✅
- dependencies
- apiRequest
- test_tenant_switch_poc.py
- get_receivable
- simulator.py
- SRIClient
- masters.py
- invoices-a11y.spec.ts
- execute_idempotent
- receivables-a11y.spec.ts
- Plugin Development Standards
- IAERP - Claude AI Assistant Configuration
- auth.tsx
- keycloak_poc.py
- serve
- tasks.py
- validate_migrations.py
- test_crm_features.py
- ERP Domain Knowledge Skill
- plugins
- validate_contracts.py
- scripts
- CrmKanban.tsx
- crm-kanban-advanced.spec.ts
- debug4.spec.ts
- configure-staging.sh
- API Reference
- get_session
- env.py
- package.json
- a11y.spec.ts
- health.py
- check_ci_services.py
- invoices.spec.ts
- tsconfig.json
- graphify.js
- __init__.py
- __init__.py
- __init__.py
- __init__.py
- __init__.py
- __init__.py
- __init__.py
- @dnd-kit/utilities
- @tanstack/react-query
- typescript
- crm-kanban.spec.ts
- 01-keycloak.sh
- iaerp-backend
- ARIA Patterns and Testing
- Coding Style Reference
- Plugin Sharing and Marketplace Publishing
- Accessibility Testing Snippets (Playwright + axe-core)
- Playwright Accessibility Testing (TypeScript)
- README.md
- Pruebas y calidad
- MCP Patterns
- Sistema de interfaz ERP
- Decision
- Estado actual y relevo
- Manual audit checklist (WCAG 2.1 Level AA / W3C WAI)
- Development Architecture Reference
- Entidades principales
- Arquitectura
- IA y MCP
- Product backlog
- 🚀 Quick Start - IAERP Development Guide
- AGENTS.md
- MCP Version Matrix
- test_mcp_prompt_injection.py
- Backlog IAERP - Alcance y Planificación
- Alcance MVP
- Migracion desde sky-franquicia
- Sprint 2 - Facturacion electronica y SRI
- Sprint 3 - Cuentas por cobrar
- MCP Audit Runbook
- Roadmap
- Operaciones
- Sprint 1 - Plataforma, identidad y maestros
- Schema Reference
- Rule Categories
- Vision de producto
- Seguridad y modelo de amenazas
- Despliegue de staging en Coolify (server .12) para pruebas online
- Evidencia: validacion MCP con Inspector real (Sprint 1)
- Migracion skyfranquicias — Fase 0: empresas B2B -> tenants
- IAERP
- Naming Conventions
- TAM, SAM y SOM
- Modelo operativo de agentes expertos
- ADR 0009: Tenant activo y compatibilidad OAuth MCP
- Sprint 0 - Definicion, riesgos y contratos
- Backend Platform Expert
- Ecuador SRI Expert
- Frontend Accessibility Expert
- MCP AI Security Expert
- Product ERP Expert
- QA Reliability Expert
- Database Model Standards
- FastAPI Best Architecture
- Scanning Patterns
- Key Workflows
- Configuration Reference
- MCP Server Pre-Deployment Checklist
- 🗓️ Backlog por Sprint
- 📊 Resumen del Alcance
- 🚨 Riesgos y Mitigaciones
- ADR 0001: Monolito modular
- ADR 0002: Keycloak para identidad OAuth/OIDC
- ADR 0003: MCP como adaptador de casos de uso
- ADR 0004: Precision monetaria
- ADR 0006: Outbox, Celery y Redis
- ADR 0007: Un RUC por tenant
- Dialog (Modal)
- Accessible Names
- Focus Management
- Visual Accessibility
- Core Principles
- Sprint 1: CRM Kanban Foundation (Semana 1)
- Sprint 3: Sidebar Colapsible (Semana 3)
- Sprint 4: Invoice Spreadsheet UX (Semana 4-5)
- Sprint 5: Forms Verticales "One Sprint" (Semana 6-7)
- Sprint 6: Pagos por Cliente (Semana 8)
- Sprint 7: Stack Modernization (Semana 9)
- Sprint 8: Polish & Animations (Semana 10-11)
- Sprint 9: Testing & Documentation (Semana 12)
- Contribucion
- React + TypeScript + Vite
- Accordion
- Tabs
- advanced-composition.md
- advanced-resources.md
- apps-ui.md
- auth-oauth21.md
- client-patterns.md
- elicitation.md
- registry-discovery.md
- sampling-tools.md
- security-hardening.md
- security-injection.md
- server-setup.md
- server-transport.md
- _template.md
- testing-debugging.md
- webmcp-browser.md
- README.md

## God Nodes (most connected - your core abstractions)
1. `APIModel` - 60 edges
2. `require_scopes()` - 59 edges
3. `Receivable` - 53 edges
4. `Movement` - 41 edges
5. `execute_idempotent()` - 41 edges
6. `Base` - 39 edges
7. `UUIDPrimaryKeyMixin` - 38 edges
8. `TimestampMixin` - 38 edges
9. `Party` - 38 edges
10. `_setup_billing_masters()` - 36 edges

## Surprising Connections (you probably didn't know these)
- `post_lead()` --calls--> `execute_idempotent()`  [INFERRED]
  backend/app/api/crm.py → backend/app/services/unit_of_work.py
- `post_lead_with_party()` --calls--> `execute_idempotent()`  [INFERRED]
  backend/app/api/crm.py → backend/app/services/unit_of_work.py
- `put_lead()` --calls--> `execute_idempotent()`  [INFERRED]
  backend/app/api/crm.py → backend/app/services/unit_of_work.py
- `put_lead_status()` --calls--> `execute_idempotent()`  [INFERRED]
  backend/app/api/crm.py → backend/app/services/unit_of_work.py
- `post_lead_message()` --calls--> `execute_idempotent()`  [INFERRED]
  backend/app/api/crm.py → backend/app/services/unit_of_work.py

## Import Cycles
- None detected.

## Communities (203 total, 33 thin omitted)

### Community 0 - "_setup_billing_masters"
Cohesion: 0.08
Nodes (66): auth(), _invoice_payload(), UUID, ``InvoiceInput`` no declara subtotal/tax/total: si el cliente los envia     igua, Sprint 3 Fase 2: ``installments`` persiste en ``sales_document_installments``., Sin plan de pago, el backend crea una sola cuota al contado = total.      La UI, Crea establishment/emission-point/party/product usados por una factura., _setup_billing_masters() (+58 more)

### Community 1 - "App.tsx"
Cohesion: 0.04
Nodes (58): AccountItem, AccountItemStatus, ApiError, ArtifactDownload, CollectionPolicy, CreditNoteInput, DiscountInput, DocumentArtifact (+50 more)

### Community 2 - "get_settings"
Cohesion: 0.06
Nodes (57): get_settings(), Settings, _client(), _content_type_for_artifact(), download_artifact(), _download_sync(), _ensure_bucket_sync(), generate_presigned_download_url() (+49 more)

### Community 3 - "handle_invoice_authorized"
Cohesion: 0.07
Nodes (63): _build_installments(), _existing_receivable(), handle_credit_note_authorized(), handle_invoice_authorized(), _load_document_installments(), AsyncSession, AuthContext, date (+55 more)

### Community 4 - "billing.py"
Cohesion: 0.10
Nodes (58): date, Zona horaria fiscal compartida entre Billing y Receivables.  ``docs/03-domain-mo, Fecha de hoy en ``America/Guayaquil``, derivada de la hora UTC real., today_in_fiscal_timezone(), create_and_issue_credit_note(), create_artifact_download(), create_credit_note(), create_invoice_draft() (+50 more)

### Community 5 - "crm_integrations.py"
Cohesion: 0.12
Nodes (40): TenantFiscalSettings, FiscalSettingsRead, FiscalSettingsUpdate, complete_google_oauth(), disconnect_google(), disconnect_whatsapp(), _google_access_token(), google_authorization_url() (+32 more)

### Community 6 - "require_scopes"
Cohesion: 0.17
Nodes (51): delete_service_account(), get_automation(), get_collection_policy(), get_context(), get_emission_points(), get_establishments(), get_fiscal_settings(), get_invoice() (+43 more)

### Community 7 - "FastAPI"
Cohesion: 0.07
Nodes (50): readiness(), startup_readiness(), correlation_middleware(), integrity_error_handler(), lifespan(), Request, Response, ready() (+42 more)

### Community 8 - "LineInput"
Cohesion: 0.07
Nodes (30): DocumentCalculation, FiscalCalculationPolicy, LineCalculation, LineInput, new_correlation_id(), date, Decimal, _quantize_amount() (+22 more)

### Community 9 - "sign_xml"
Cohesion: 0.09
Nodes (41): generate_self_signed_p12(), Path, Genera un certificado RSA autofirmado de PRUEBA para firmar XML XAdES-BES.  Vive, Genera clave RSA-2048 + certificado autofirmado y los empaqueta en PKCS#12., certificate_fingerprint_sha256(), _default_cert_path(), _ensure_dev_certificate_exists(), load_signing_credentials() (+33 more)

### Community 10 - "build_invoice_xml"
Cohesion: 0.12
Nodes (39): build_credit_note_xml(), _build_detalles(), build_invoice_xml(), _build_tax_summary(), _buyer_identification_code(), _format_amount(), _format_quantity_or_price(), date (+31 more)

### Community 11 - "crm.py"
Cohesion: 0.12
Nodes (41): delete_google_integration(), delete_whatsapp_integration(), get_google_callback(), get_integrations(), get_lead(), get_lead_activities(), get_leads(), post_gmail_sync_now() (+33 more)

### Community 12 - "APIModel"
Cohesion: 0.06
Nodes (51): issue_dev_token(), APIModel, BaseModel, ArtifactDownloadRead, CreditNoteInput, DocumentArtifactRead, InstallmentInput, InvoiceInput (+43 more)

### Community 13 - "server.py"
Cohesion: 0.11
Nodes (38): context_get(), credit_notes_create_and_issue(), invoices_create_draft(), invoices_get(), invoices_issue(), parties_create(), parties_search(), products_search() (+30 more)

### Community 14 - "LeadsPage.tsx"
Cohesion: 0.11
Nodes (28): LeadWithPartyCreate, Product, BulkActionBar(), STAGE_LABELS, STAGES, HOTNESS_OPTIONS, KanbanFilters(), LeadDetailModal() (+20 more)

### Community 15 - "masters.py"
Cohesion: 0.13
Nodes (37): _admin_configured(), _admin_token(), _client_representation(), delete_service_account(), disable_service_account(), _find_client(), provision_service_account(), Any (+29 more)

### Community 16 - "test_mcp_receivables.py"
Cohesion: 0.09
Nodes (46): exception_text(), issue_service_token(), issue_user_token(), main(), mcp_session(), AsyncClient, BaseException, ClientSession (+38 more)

### Community 17 - "receivables.py"
Cohesion: 0.14
Nodes (32): apply_credit_note(), compute_aging_summary(), _compute_installment_open_balance(), compute_receivable_balance(), _compute_worst_aging(), get_receivable(), installment_agings_for_receivable(), list_movements() (+24 more)

### Community 18 - "Party"
Cohesion: 0.08
Nodes (42): Notifier, Protocol, Protocolo ``Notifier`` para envío de recordatorios de cobranza (Sprint 3, decisi, Solicitud de envío de recordatorio.      ``channel`` puede ser "email", "sms", ", Respuesta de ``send``.      ``reminder_id`` es el UUID del ``CollectionReminder`, Proveedor de envío de recordatorios (real o stub).      Ninguna implementación d, ReminderRequest, ReminderResult (+34 more)

### Community 19 - "OutboxMessage"
Cohesion: 0.14
Nodes (24): OutboxEvent, claim_outbox_batch(), consume_once(), dispatch_outbox_once(), EventPublisher, _mark_failed(), _mark_published(), messages_for_tenant() (+16 more)

### Community 20 - "Receivable"
Cohesion: 0.21
Nodes (32): Cabecera de cartera 1:1 con la factura ``AUTHORIZED`` que la origina.      Cread, Receivable, PaymentInput, Cobro parcial o total, con retenciones/descuentos anidados (E5-03/E5-04).      L, lock_receivable(), PaymentInput, Lock exclusivo sobre un ``Receivable`` con ``SELECT ... FOR UPDATE``.      Seria, Registra un cobro parcial o total con retenciones/descuentos (E5-03/E5-04). (+24 more)

### Community 21 - "test_access_key.py"
Cohesion: 0.11
Nodes (28): AccessKeyInput, build_access_key(), compute_verifier_digit(), generate_numeric_code(), Clave de acceso SRI (49 digitos) y su digito verificador modulo 11.  Formato ofi, Construye la clave de acceso SRI de 49 digitos a partir de sus partes.      Vali, Genera un codigo numerico de control de 8 digitos, no criptografico.      El cod, Revalida el digito verificador de una clave de acceso ya construida. (+20 more)

### Community 22 - "handle_invoice_signed"
Cohesion: 0.16
Nodes (29): _apply_authorization_result(), _apply_reception_result(), _dead_letter(), _default_sri_client(), _enqueue_followup(), _followup_or_dead_letter(), handle_invoice_signed(), _latest_transmission_for_access_key() (+21 more)

### Community 23 - "test_receivables_aging.py"
Cohesion: 0.15
Nodes (27): classify_aging_bucket(), Clasifica una cuota en su bucket de aging según días de mora.      Función pura, _context(), _create_receivable_with_installments(), AuthContext, date, Decimal, UUID (+19 more)

### Community 24 - "AuthContext"
Cohesion: 0.15
Nodes (19): AccessToken, AuthContext, create_dev_token(), decode_access_token(), _extract_organization_id(), get_auth_context(), AsyncSession, Depends (+11 more)

### Community 25 - "receivables.py"
Cohesion: 0.09
Nodes (24): get_receivables_aging(), Resumen de aging por tenant (Sprint 3 Fase 3: E5-05).      Declarado ANTES de ``, AgingBucketTotalRead, AgingRead, AgingSummaryRead, CollectionPolicyRead, CollectionPolicyUpdate, DiscountInput (+16 more)

### Community 26 - "Base"
Cohesion: 0.14
Nodes (42): Base, TimestampMixin, UUIDPrimaryKeyMixin, MastersSeedResult, date, Ids resueltos por ``_seed_masters`` que ``_seed_billing`` necesita.      ``tax_c, _seed_masters(), DocumentArtifact (+34 more)

### Community 27 - "Movement"
Cohesion: 0.25
Nodes (25): Movement, Aplicacion sobre una cuota: pago, retencion, descuento, NC o reverso.      Defin, Revierte un movimiento creando un ``REVERSAL`` que lo deshace (E5-09).      El m, reverse_movement(), _context(), _create_receivable_via_event_http(), AuthContext, Decimal (+17 more)

### Community 28 - "useKanban.ts"
Cohesion: 0.14
Nodes (21): Lead, LeadStatus, CrmKanbanProps, HOTNESS_COLORS, LeadCard(), LeadCardProps, STAGE_COLORS, buildOptimisticLead() (+13 more)

### Community 29 - "initial_data.py"
Cohesion: 0.23
Nodes (23): _build_access_key(), _ensure_sequence_floor(), AsyncSession, datetime, Decimal, SalesDocument, UUID, Create reproducible local hashes without storing a usable plaintext secret. (+15 more)

### Community 30 - "SimulatorSRIClient"
Cohesion: 0.19
Nodes (20): Cliente ``SRIClient`` in-process contra el ``ScenarioStore`` singleton.      No, Store en memoria, thread-safe, de escenarios por clave de acceso., ScenarioStore, SimulatorSRIClient, client(), Pruebas unitarias del simulador SRI (los 6 comportamientos, E4-04).  El escenari, DUPLICATE_RESPONSE: el simulador siempre re-entrega la misma autorizacion., Sin escenario configurado: RECEIVED en recepcion, PENDING luego AUTHORIZED. (+12 more)

### Community 31 - "compilerOptions"
Cohesion: 0.08
Nodes (23): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+15 more)

### Community 32 - "SalesDocument"
Cohesion: 0.17
Nodes (23): seed(), DocumentRelation, Relacion nota de credito -> factura autorizada que compensa., Siguiente valor de secuencial por tenant/establecimiento/punto/tipo.      La res, Cada intento de transmision al SRI (o al simulador), con su respuesta.      Esta, Cabecera comun de factura y nota de credito.      Estados: DRAFT -> READY -> SIG, Linea de un ``SalesDocument`` con el impuesto ya cuantizado.      ``tax_sri_code, SalesDocument (+15 more)

### Community 33 - "build_ride_pdf"
Cohesion: 0.14
Nodes (23): _access_key_as_text_groups(), build_ride_pdf(), _format_amount(), _format_quantity_or_price(), _full_document_number(), Decimal, EmissionPoint, Establishment (+15 more)

### Community 34 - "get_store"
Cohesion: 0.21
Nodes (17): get_store(), _claim_signed_event(), _create_draft(), _issue(), Integracion Fase 4 (E4-04/E4-05/E4-08): emision, transmision, reconciliacion.  C, E4-05: con una transmision RECEIVED previa, un TIMEOUT en recepcion nunca     de, _reset_simulator(), test_duplicate_response_scenario_does_not_create_second_authorization() (+9 more)

### Community 35 - "_create_authorized_invoice_stub"
Cohesion: 0.29
Nodes (21): compute_installment_balance(), Calcula el saldo de una cuota sumando sus movimientos activos.      Cuenta solo, _create_authorized_invoice_stub(), _create_party(), _create_receivable(), date, Decimal, Party (+13 more)

### Community 36 - "compilerOptions"
Cohesion: 0.10
Nodes (19): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+11 more)

### Community 37 - "devDependencies"
Cohesion: 0.11
Nodes (19): axe-core, @axe-core/playwright, devDependencies, axe-core, @axe-core/playwright, oxlint, @playwright/test, @types/node (+11 more)

### Community 38 - "🟢 Tareas COMPLETADAS (10) - SPRINT 1 COMPLETADO ✅"
Cohesion: 0.04
Nodes (46): 💾 Backup y Recovery, 🚨 Emergency Procedures, Esta semana:, Inmediato (Próxima sesión):, Issue Tracking - Sesión por Sesión, 🎯 Next Actions (Ordered by Priority), 🎯 Objetivo de este Documento, Overall Progress (0%) (+38 more)

### Community 39 - "dependencies"
Cohesion: 0.11
Nodes (19): @dnd-kit/core, @dnd-kit/sortable, @fontsource-variable/manrope, @fontsource-variable/newsreader, framer-motion, dependencies, @dnd-kit/core, @dnd-kit/sortable (+11 more)

### Community 40 - "apiRequest"
Cohesion: 0.22
Nodes (18): apiRequest(), idempotencyKey(), addDays(), CreditNoteForm(), emptyDraftLine(), formatAmount(), formatPercent(), InvoiceDetail() (+10 more)

### Community 41 - "test_tenant_switch_poc.py"
Cohesion: 0.29
Nodes (15): _decode_unverified(), _get_context(), http(), _password_grant(), Any, AsyncClient, Response, PoC automatizado del cambio de tenant OIDC multi-tenant (ADR 0009).  Comprueba c (+7 more)

### Community 42 - "get_receivable"
Cohesion: 0.20
Nodes (14): alias, _account_item_response(), get_invoices(), get_parties(), get_receivable(), get_receivables(), date, min_length (+6 more)

### Community 43 - "simulator.py"
Cohesion: 0.15
Nodes (11): _AccessKeyState, get_scenario(), BaseModel, Simulador SRI propio (in-memory) para Sprint 2 (no existe ambiente de pruebas SR, Fija el escenario de una clave de acceso para la proxima transmision.      Solo, Limpia todos los escenarios configurados (aislamiento entre pruebas)., Estado simulado de una clave de acceso.      ``behavior`` es el escenario config, reset_scenarios() (+3 more)

### Community 44 - "SRIClient"
Cohesion: 0.15
Nodes (8): AuthorizationResult, Protocol, Contrato ``SRIClient`` para transmision y consulta de autorizacion SRI.  ``docs/, Respuesta de ``send_reception``. ``messages`` son mensajes SRI crudos.      ``me, Respuesta de ``check_authorization``.      ``authorization_number`` y ``authoriz, Cliente de transmision SRI (real o simulado).      Ninguna implementacion decide, ReceptionResult, SRIClient

### Community 45 - "masters.py"
Cohesion: 0.18
Nodes (13): products_create(), Crear un producto con idempotencia y politica de automatizacion., EmissionPointCreate, EmissionPointRead, EstablishmentCreate, EstablishmentRead, PartyCreate, PartyRead (+5 more)

### Community 46 - "invoices-a11y.spec.ts"
Cohesion: 0.15
Nodes (8): authorizedInvoice, context, customer, draftInvoice, emissionPoint, establishment, product, rejectedInvoice

### Community 47 - "execute_idempotent"
Cohesion: 0.27
Nodes (11): post_signing_certificate(), max_length, append_audit(), canonical_hash(), execute_idempotent(), Any, AsyncSession, AuthContext (+3 more)

### Community 48 - "receivables-a11y.spec.ts"
Cohesion: 0.18
Nodes (6): context, customer, overdueReceivable, partialReceivable, settledReceivable, updatedAfterPayment

### Community 49 - "Plugin Development Standards"
Cohesion: 0.04
Nodes (44): App-level Plugin, App-level Plugin Configuration, App-level Routes, Backend Plugin Directory Structure, Canonical Output Contract, Common Plugin Metadata, Configuration, Contact (+36 more)

### Community 50 - "IAERP - Claude AI Assistant Configuration"
Cohesion: 0.05
Nodes (36): Backend, Backend, Backend, Branch strategy:, Commit messages:, Configuración de Agentes IA, Contacto y Soporte, Contexto del Proyecto (+28 more)

### Community 51 - "auth.tsx"
Cohesion: 0.29
Nodes (8): configureApiTokenProvider(), AuthContext, AuthProvider(), AuthState, keycloak, readStoredAuth(), StoredAuth, queryClient

### Community 52 - "keycloak_poc.py"
Cohesion: 0.44
Nodes (9): decode(), has_audience(), issue_service_token(), issue_user_token(), main(), Any, Response, selected_organization() (+1 more)

### Community 53 - "serve"
Cohesion: 0.53
Nodes (4): CeleryPublisher, main(), publish_heartbeat(), serve()

### Community 54 - "tasks.py"
Cohesion: 0.31
Nodes (7): _acknowledge_event(), consume_event(), AsyncSession, _resolve_consumer(), _run(), Handler, T

### Community 55 - "validate_migrations.py"
Cohesion: 0.44
Nodes (8): admin_connection(), alembic(), assert_downgraded_to_base(), database_url(), main(), reset_database(), Connection, URL

### Community 56 - "test_crm_features.py"
Cohesion: 0.50
Nodes (8): auth(), UUID, Regresion: el body incluye lead_id (schema) y el path tambien; el     servicio d, test_crm_and_integrations_require_their_declared_scopes(), test_invoice_preview_and_collection_policy_are_server_authoritative(), test_lead_activity_creation_returns_201_and_ignores_body_lead_id(), test_lead_with_new_contact_has_title_summary_owner_and_customer_conversion(), token_for()

### Community 57 - "ERP Domain Knowledge Skill"
Cohesion: 0.07
Nodes (29): 1. Finance & Accounting, 2. Human Resources (HR), 3. Supply Chain Management (SCM), 4. Manufacturing, 5. Project Management, Common Integrations, Compliance, Compliance & Security (+21 more)

### Community 58 - "plugins"
Cohesion: 0.22
Nodes (8): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema, oxc, typescript, warn

### Community 59 - "validate_contracts.py"
Cohesion: 0.54
Nodes (7): load_yaml(), main(), Any, Path, references(), resolve_reference(), validate_mcp()

### Community 60 - "scripts"
Cohesion: 0.29
Nodes (7): scripts, build, dev, lint, preview, test:e2e, test:e2e:oidc

### Community 61 - "CrmKanban.tsx"
Cohesion: 0.38
Nodes (4): ACTIVE_STAGES, CrmKanban(), KanbanColumnProps, PIPELINE

### Community 62 - "crm-kanban-advanced.spec.ts"
Cohesion: 0.33
Nodes (4): context, mockCrmApi(), product, seedLeads()

### Community 63 - "debug4.spec.ts"
Cohesion: 0.33
Nodes (4): context, mockCrmApi(), product, seedLeads()

### Community 64 - "configure-staging.sh"
Cohesion: 0.43
Nodes (4): ensure_default_scope(), reset_user_password(), configure-staging.sh script, update_client_secret()

### Community 65 - "API Reference"
Cohesion: 0.08
Nodes (25): API Authentication, API Documentation Rules, API Reference, Camel Case Response, CurrentSession (Read-only Session), CurrentSessionTransaction (Transaction Session), Database Transaction, Dynamic Switching (+17 more)

### Community 66 - "get_session"
Cohesion: 0.40
Nodes (4): enable_sqlite_foreign_keys(), get_session(), Any, AsyncSession

### Community 67 - "env.py"
Cohesion: 0.60
Nodes (3): do_run_migrations(), run_async_migrations(), run_migrations_online()

### Community 68 - "package.json"
Cohesion: 0.40
Nodes (4): name, private, type, version

### Community 70 - "health.py"
Cohesion: 0.83
Nodes (3): check_dispatcher(), check_worker(), main()

### Community 71 - "check_ci_services.py"
Cohesion: 0.83
Nodes (3): check_postgres(), check_redis(), main()

### Community 106 - "ARIA Patterns and Testing"
Cohesion: 0.10
Nodes (21): ARIA Fundamentals, ARIA Patterns and Testing, ARIA Roles Categories, Combobox (Autocomplete), Common ARIA Mistakes, Live Regions, Menu (Dropdown), Quick Reference: Roles and Required States (+13 more)

### Community 107 - "Coding Style Reference"
Cohesion: 0.10
Nodes (20): Additional Requirements, API Route Documentation, Async Handling, Code Formatting, Coding Style Reference, Comments, Core Rule, Docstring Format (+12 more)

### Community 108 - "Plugin Sharing and Marketplace Publishing"
Cohesion: 0.12
Nodes (16): Agent Safety, Backend Plugin, Backend Plugin Repository, Backend Repository Root, Frontend Plugin, Frontend Plugin Repository, Frontend Repository Root, Installation Notes for Shared Plugins (+8 more)

### Community 109 - "Accessibility Testing Snippets (Playwright + axe-core)"
Cohesion: 0.12
Nodes (16): Accessibility Testing Snippets (Playwright + axe-core), Axe-Core Helper, Form Keyboard Navigation, Form Labels, Heading Hierarchy, Install Dependencies, Keyboard Navigation, Landmarks Validation (+8 more)

### Community 110 - "Playwright Accessibility Testing (TypeScript)"
Cohesion: 0.13
Nodes (15): Axe-Core Tags Reference, CLI Quick Reference, Common Rationalizations, Default Tags (WCAG 2.1 AA), Exception Handling, External Resources, First Questions to Ask, Playwright Accessibility Testing (TypeScript) (+7 more)

### Community 111 - "README.md"
Cohesion: 0.14
Nodes (9): Agentes expertos de IAERP, Registro, Reglas, Revision de cadena de suministro, Skills instaladas, Contratos preliminares, Convenciones, 📊 Progreso General (+1 more)

### Community 112 - "Pruebas y calidad"
Cohesion: 0.14
Nodes (13): CI, Cobertura, Datos de prueba, Definition of Done, Dinero, Escenarios obligatorios, Facturacion, IA/MCP (+5 more)

### Community 113 - "MCP Patterns"
Cohesion: 0.15
Nodes (12): Common Mistakes, Debugging with Claude Code, Decision Tree — Which Rule to Read, Ecosystem, Example, Feature Maturity, Key Decisions, MCP Patterns (+4 more)

### Community 114 - "Sistema de interfaz ERP"
Cohesion: 0.15
Nodes (12): Accesibilidad, Acciones estandar, Componentes base, Configuracion, Crear y editar, Dashboard, Ficha, Listado (+4 more)

### Community 115 - "Decision"
Cohesion: 0.15
Nodes (12): 1. Orden de cantidad, precio y descuento (por linea), 2. Base imponible por tarifa (agregacion), 3. Totales del documento, 4. Precision intermedia y cuantizacion (resumen normativo), 5. Notas de credito (esquema 1.1.0), 6. Tarifas vigentes en `ec-iva-v1`, ADR 0008: Calculo fiscal y redondeo versionado, Consecuencias (+4 more)

### Community 116 - "Estado actual y relevo"
Cohesion: 0.15
Nodes (12): Avance de Sprint 2 (corte 2026-07-04), Avance de Sprint 3 y Epic E7 (corte 2026-07-09), Avance Sprint 3 (corte 2026-07-06), Corte verificado, Ejecucion local, Estado actual y relevo, Estado por fase, Implementado en Sprint 1 (+4 more)

### Community 117 - "Manual audit checklist (WCAG 2.1 Level AA / W3C WAI)"
Cohesion: 0.17
Nodes (8): Assistive technology and real-user checks, Documentation and exception handling, Manual audit checklist (WCAG 2.1 Level AA / W3C WAI), Operable, Perceivable, Robust, Understandable, W3C/WAI references

### Community 118 - "Development Architecture Reference"
Cohesion: 0.17
Nodes (11): Cache, Celery and Background Work, Code Generation, Development Architecture Reference, Docker and Local Runtime Notes, I18n, Implementation Flow, Layer Responsibilities (+3 more)

### Community 119 - "Entidades principales"
Cohesion: 0.17
Nodes (11): Contextos, Cuentas por cobrar, Cuentas por pagar, Datos maestros, Entidades principales, Eventos de dominio iniciales, Facturacion, Identidad y organizacion (+3 more)

### Community 120 - "Arquitectura"
Cohesion: 0.17
Nodes (11): Archivos y secretos, Arquitectura, Asincronia e idempotencia, Backend, Componentes, Criterios para separar servicios, Despliegue, Enfoque (+3 more)

### Community 121 - "IA y MCP"
Cohesion: 0.17
Nodes (11): Catalogo inicial, Consulta, Documentos no confiables, Escritura, Flujo de una escritura, IA y MCP, Objetivo, Politicas autonomas (+3 more)

### Community 122 - "Product backlog"
Cohesion: 0.17
Nodes (12): Epic E0 - Producto y gobierno, Epic E1 - Identidad y aislamiento, Epic E2 - Plataforma segura, Epic E3 - Maestros, Epic E4 - Facturacion electronica, Epic E5 - Cuentas por cobrar, Epic E6 - Cuentas por pagar, Epic E7 - IA y MCP (+4 more)

### Community 123 - "🚀 Quick Start - IAERP Development Guide"
Cohesion: 0.17
Nodes (11): 📁 Documentation Structure (4 key files), 📞 Emergency Commands, 🎓 Learning Resources, 📊 Progress Overview, ⚡ Quick Actions, 🆘 Quick Help, 🔄 Quick Resume (20 seconds), 🚀 Quick Start - IAERP Development Guide (+3 more)

### Community 124 - "AGENTS.md"
Cohesion: 0.18
Nodes (9): Coordinacion de expertos, Entrega, graphify, Interfaz, Politica de ramas, Pruebas, Puerta documental, Reglas de dominio (+1 more)

### Community 125 - "MCP Version Matrix"
Cohesion: 0.18
Nodes (10): Audit Cadence Calibration, Audit Method, How to Re-run This Audit, Matrix, MCP Version Matrix, Recommendations Status, References, Risk Tier (unchanged) (+2 more)

### Community 126 - "test_mcp_prompt_injection.py"
Cohesion: 0.20
Nodes (10): E7-07: resistir prompt injection (fixtures maliciosos no ejecutan tools).  Postu, Un payload de inyeccion en `Product.name` vuelve como texto plano por MCP., Un `reference`/`reason` de cobro con payload de inyeccion se almacena como dato., El catalogo completo es la lista cerrada esperada; no hay tool de SQL libre., Un payload de inyeccion en `Party.name` vuelve como texto plano por MCP., _tax_category_id(), test_mcp_prompt_injection_party_name_returns_as_inert_plain_text(), test_mcp_prompt_injection_payment_reference_and_discount_reason_are_inert() (+2 more)

### Community 127 - "Backlog IAERP - Alcance y Planificación"
Cohesion: 0.18
Nodes (10): Backlog IAERP - Alcance y Planificación, Business Metrics, Checklist por Sprint:, 🔄 Cierre de Sprint, 📞 Contacto y Soporte, Development Metrics, Formato de Status Update:, 📈 Métricas de Éxito (+2 more)

### Community 128 - "Alcance MVP"
Cohesion: 0.18
Nodes (10): Alcance MVP, Alcance y restricciones, Cuentas por cobrar, Cuentas por pagar, Facturacion, Fuera del MVP, IA y MCP, Limites de autonomia (+2 more)

### Community 129 - "Migracion desde sky-franquicia"
Cohesion: 0.18
Nodes (10): Certificados, Criterios de aceptacion, Cutover y delta, Mapeo, Migracion desde sky-franquicia, Objetivo, Pipeline, Reporte obligatorio (+2 more)

### Community 130 - "Sprint 2 - Facturacion electronica y SRI"
Cohesion: 0.18
Nodes (10): Criterios de aceptacion, Decisiones de diseno, Estado, Historias, No incluido, Objetivo, Plan de pruebas y datos, Revisiones obligatorias (+2 more)

### Community 131 - "Sprint 3 - Cuentas por cobrar"
Cohesion: 0.18
Nodes (10): Criterios de aceptacion, Decisiones de diseno, Estado, Historias, No incluido, Objetivo, Plan de pruebas y datos, Revisiones obligatorias (+2 more)

### Community 132 - "MCP Audit Runbook"
Cohesion: 0.20
Nodes (9): CC 2.1.128: MCP Reconnect Tool Summarization, Escape hatch: pin a specific version, Interpreting output, MCP Audit Runbook, Re-run script, Related, Updating the matrix, When to escalate to a full consumer audit (+1 more)

### Community 133 - "Roadmap"
Cohesion: 0.20
Nodes (9): Puertas, Roadmap, Sprint 0 - Definicion y contratos, Sprint 1 - Plataforma y maestros, Sprint 2 - Facturacion, Sprint 3 - Cuentas por cobrar, Sprint 4 - Cuentas por pagar, Sprint 5 - Automatizacion y migracion piloto (+1 more)

### Community 134 - "Operaciones"
Cohesion: 0.20
Nodes (9): Ambientes, Backup y restauracion, Despliegue, Incidentes, Observabilidad, Operaciones, Retencion, Runbooks (+1 more)

### Community 135 - "Sprint 1 - Plataforma, identidad y maestros"
Cohesion: 0.20
Nodes (9): Criterios de aceptacion, Estado, Historias, No incluido, Objetivo, Plan de pruebas y datos, Revisiones obligatorias, Secuencia tecnica (+1 more)

### Community 136 - "Schema Reference"
Cohesion: 0.22
Nodes (8): Base Class Usage, Camel Case Response, Complete Example, description Parameter, Field Definition, Optional Fields, Required Fields, Schema Reference

### Community 137 - "Rule Categories"
Cohesion: 0.22
Nodes (8): 1. Server (server) — HIGH — 2 rules, 2. Auth (auth) — HIGH — 1 rule, 3. Advanced (advanced) — MEDIUM — 5 rules, 4. Client (client) — MEDIUM — 1 rule, 5. Security (security) — HIGH — 2 rules, 6. Quality (quality) — MEDIUM — 1 rule, 7. Ecosystem (ecosystem) — LOW — 2 rules, Rule Categories

### Community 138 - "Vision de producto"
Cohesion: 0.22
Nodes (8): Cliente ideal, Indicadores iniciales, No objetivos del MVP, Principios, Problema, Propuesta, Resultados esperados del MVP, Vision de producto

### Community 139 - "Seguridad y modelo de amenazas"
Cohesion: 0.22
Nodes (8): Activos, Amenazas y controles, Auditoria, Fronteras de confianza, Privacidad, Reglas de secretos, Seguridad y modelo de amenazas, Validacion de seguridad

### Community 140 - "Despliegue de staging en Coolify (server .12) para pruebas online"
Cohesion: 0.22
Nodes (8): Checklist antes de abrir el acceso, Despliegue de staging en Coolify (server .12) para pruebas online, Keycloak: realm e usuarios, Postura de seguridad (obligatoria), Que NO hace staging, Rama y flujo, Servicios a desplegar, Variables de entorno (se configuran en Coolify, NUNCA en Git)

### Community 141 - "Evidencia: validacion MCP con Inspector real (Sprint 1)"
Cohesion: 0.22
Nodes (8): Catalogo de tools filtrado por scopes de la service account, Conclusiones, `context.get` resuelve el tenant de cada agente, Emision de tokens (client credentials por tenant), Evidencia: validacion MCP con Inspector real (Sprint 1), `parties.search` devuelve solo datos del tenant del token, Protected Resource Metadata, Request sin token: 401 con puntero al PRM

### Community 142 - "Migracion skyfranquicias — Fase 0: empresas B2B -> tenants"
Cohesion: 0.22
Nodes (8): Criterios de aceptacion (Fase 0), Decisiones de esta fase (2026-07-09), Idempotencia y rollback, Lo que falta para ejecutar (input del owner), Migracion skyfranquicias — Fase 0: empresas B2B -> tenants, Pipeline (subconjunto de docs/07-data-migration.md), Que NO entra en Fase 0, Trabajo tecnico previsto en IAERP (cuando haya inputs)

### Community 143 - "IAERP"
Cohesion: 0.22
Nodes (9): Alcance inicial, Documentacion, Documentos de Producto:, Entrega, Estado, Guías Rápidas:, IAERP, Planificación y Alcance: (+1 more)

### Community 144 - "Naming Conventions"
Cohesion: 0.25
Nodes (7): API Function Naming And Definition Order, Class Naming, CRUD Method Naming And Definition Order, File and Directory Naming, Naming Conventions, Schema Naming And Definition Order, Service Method Naming And Definition Order

### Community 145 - "TAM, SAM y SOM"
Cohesion: 0.25
Nodes (7): Fecha y fuentes, Hipotesis comercial, SAM, SOM a tres anos, TAM, TAM, SAM y SOM, Validaciones pendientes

### Community 146 - "Modelo operativo de agentes expertos"
Cohesion: 0.25
Nodes (7): Autoridad humana reservada, Flujo, Independencia, Matriz de revision, Modelo operativo de agentes expertos, Objetivo, Skills

### Community 147 - "ADR 0009: Tenant activo y compatibilidad OAuth MCP"
Cohesion: 0.25
Nodes (7): ADR 0009: Tenant activo y compatibilidad OAuth MCP, Consecuencias, Contexto, Decision propuesta, Fuentes, PoC bloqueante, Resultado del PoC (2026-07-03, Keycloak 26.6.4)

### Community 148 - "Sprint 0 - Definicion, riesgos y contratos"
Cohesion: 0.25
Nodes (7): Criterios de aceptacion, Decision de cierre, Duracion y objetivo, Entregables, Estado, Riesgos a resolver antes de Sprint 1, Sprint 0 - Definicion, riesgos y contratos

### Community 149 - "Backend Platform Expert"
Cohesion: 0.29
Nodes (6): Backend Platform Expert, Checks obligatorios, Entrega, Mision, No puede, Responsabilidades

### Community 150 - "Ecuador SRI Expert"
Cohesion: 0.29
Nodes (6): Checks obligatorios, Ecuador SRI Expert, Entrega, Mision, No puede, Responsabilidades

### Community 151 - "Frontend Accessibility Expert"
Cohesion: 0.29
Nodes (6): Checks obligatorios, Entrega, Frontend Accessibility Expert, Mision, No puede, Responsabilidades

### Community 152 - "MCP AI Security Expert"
Cohesion: 0.29
Nodes (6): Checks obligatorios, Entrega, MCP AI Security Expert, Mision, No puede, Responsabilidades

### Community 153 - "Product ERP Expert"
Cohesion: 0.29
Nodes (6): Checks obligatorios, Entrega, Mision, No puede, Product ERP Expert, Responsabilidades

### Community 154 - "QA Reliability Expert"
Cohesion: 0.29
Nodes (6): Checks obligatorios, Entrega, Mision, No puede, QA Reliability Expert, Responsabilidades

### Community 155 - "Database Model Standards"
Cohesion: 0.29
Nodes (6): Complete Example, Database Migration, Database Model Standards, Field Types, Model Base Class, Primary Key Modes

### Community 156 - "FastAPI Best Architecture"
Cohesion: 0.29
Nodes (6): CLI, Core Architecture, Development Workflow, FastAPI Best Architecture, Plugin Work, Reference Selection

### Community 157 - "Scanning Patterns"
Cohesion: 0.33
Nodes (6): Component-Scoped Scan, Dynamic Content Scan, Exclude Third-Party Widgets, Full Page Scan, Multiple States Scan, Scanning Patterns

### Community 158 - "Key Workflows"
Cohesion: 0.33
Nodes (6): Automated Axe Scan (WCAG 2.1 AA), Dialog Focus Management, Key Workflows, Keyboard Navigation Test, Scoped Axe Scan (Component-Level), Skip Link Validation

### Community 159 - "Configuration Reference"
Cohesion: 0.33
Nodes (5): Common Paths, Configuration Reference, General Rules, Plugin Settings, Source Priority

### Community 160 - "MCP Server Pre-Deployment Checklist"
Cohesion: 0.33
Nodes (5): MCP Server Pre-Deployment Checklist, Resource Management, Security Hardening, Server Setup, Testing

### Community 161 - "🗓️ Backlog por Sprint"
Cohesion: 0.40
Nodes (5): 🗓️ Backlog por Sprint, Criterios de Aceptación:, Historias de Usuario:, Sprint 2: CRM Kanban Advanced (Semana 2), Tareas Técnicas:

### Community 162 - "📊 Resumen del Alcance"
Cohesion: 0.40
Nodes (5): Módulo CRM Mejoras (Sprints 1-2), Polish & Deploy (Sprints 9-12), 📊 Resumen del Alcance, Stack Technical Upgrade (Sprint 7-8), UX Modernización (Sprints 3-6)

### Community 163 - "🚨 Riesgos y Mitigaciones"
Cohesion: 0.40
Nodes (5): Riesgo 1: Drag & Drop Performance, Riesgo 2: Cálculos Fiscales Incorrectos, Riesgo 3: Regresiones en UI Refactor, Riesgo 4: Scope Creep, 🚨 Riesgos y Mitigaciones

### Community 164 - "ADR 0001: Monolito modular"
Cohesion: 0.40
Nodes (4): ADR 0001: Monolito modular, Consecuencias, Contexto, Decision

### Community 165 - "ADR 0002: Keycloak para identidad OAuth/OIDC"
Cohesion: 0.40
Nodes (4): ADR 0002: Keycloak para identidad OAuth/OIDC, Consecuencias, Contexto, Decision

### Community 166 - "ADR 0003: MCP como adaptador de casos de uso"
Cohesion: 0.40
Nodes (4): ADR 0003: MCP como adaptador de casos de uso, Consecuencias, Contexto, Decision

### Community 167 - "ADR 0004: Precision monetaria"
Cohesion: 0.40
Nodes (4): ADR 0004: Precision monetaria, Consecuencias, Contexto, Decision

### Community 168 - "ADR 0006: Outbox, Celery y Redis"
Cohesion: 0.40
Nodes (4): ADR 0006: Outbox, Celery y Redis, Consecuencias, Contexto, Decision

### Community 169 - "ADR 0007: Un RUC por tenant"
Cohesion: 0.40
Nodes (4): ADR 0007: Un RUC por tenant, Consecuencias, Contexto, Decision

### Community 170 - "Dialog (Modal)"
Cohesion: 0.50
Nodes (4): Dialog (Modal), Focus Trap Test, Required ARIA, Test Pattern

### Community 171 - "Accessible Names"
Cohesion: 0.50
Nodes (4): Accessible Names, Buttons Have Names, Images Have Alt Text, Links Have Purpose

### Community 172 - "Focus Management"
Cohesion: 0.50
Nodes (4): Dialog Focus Trap, Focus Management, Menu Focus Management, Toast/Alert Focus

### Community 173 - "Visual Accessibility"
Cohesion: 0.50
Nodes (4): Focus Visibility, High Contrast Mode, Reduced Motion, Visual Accessibility

### Community 174 - "Core Principles"
Cohesion: 0.50
Nodes (4): 1. Automation Limitations, 2. Semantic HTML First, 3. Locator Strategy as A11y Signal, Core Principles

### Community 175 - "Sprint 1: CRM Kanban Foundation (Semana 1)"
Cohesion: 0.50
Nodes (4): Criterios de Aceptación:, Historias de Usuario:, Sprint 1: CRM Kanban Foundation (Semana 1), Tareas Técnicas:

### Community 176 - "Sprint 3: Sidebar Colapsible (Semana 3)"
Cohesion: 0.50
Nodes (4): Criterios de Aceptación:, Historias de Usuario:, Sprint 3: Sidebar Colapsible (Semana 3), Tareas Técnicas:

### Community 177 - "Sprint 4: Invoice Spreadsheet UX (Semana 4-5)"
Cohesion: 0.50
Nodes (4): Criterios de Aceptación:, Historias de Usuario:, Sprint 4: Invoice Spreadsheet UX (Semana 4-5), Tareas Técnicas:

### Community 178 - "Sprint 5: Forms Verticales "One Sprint" (Semana 6-7)"
Cohesion: 0.50
Nodes (4): Criterios de Aceptación:, Historias de Usuario:, Sprint 5: Forms Verticales "One Sprint" (Semana 6-7), Tareas Técnicas:

### Community 179 - "Sprint 6: Pagos por Cliente (Semana 8)"
Cohesion: 0.50
Nodes (4): Criterios de Aceptación:, Historias de Usuario:, Sprint 6: Pagos por Cliente (Semana 8), Tareas Técnicas:

### Community 180 - "Sprint 7: Stack Modernization (Semana 9)"
Cohesion: 0.50
Nodes (4): Criterios de Aceptación:, Historias de Usuario:, Sprint 7: Stack Modernization (Semana 9), Tareas Técnicas:

### Community 181 - "Sprint 8: Polish & Animations (Semana 10-11)"
Cohesion: 0.50
Nodes (4): Criterios de Aceptación:, Historias de Usuario:, Sprint 8: Polish & Animations (Semana 10-11), Tareas Técnicas:

### Community 182 - "Sprint 9: Testing & Documentation (Semana 12)"
Cohesion: 0.50
Nodes (4): Criterios de Aceptación:, Historias de Usuario:, Sprint 9: Testing & Documentation (Semana 12), Tareas Técnicas:

### Community 183 - "Contribucion"
Cohesion: 0.50
Nodes (3): Contribucion, Definition of Done, Flujo

### Community 184 - "React + TypeScript + Vite"
Cohesion: 0.50
Nodes (3): Expanding the Oxlint configuration, React Compiler, React + TypeScript + Vite

### Community 185 - "Accordion"
Cohesion: 0.67
Nodes (3): Accordion, Required ARIA, Test Pattern

### Community 186 - "Tabs"
Cohesion: 0.67
Nodes (3): Required ARIA, Tabs, Test Pattern

## Knowledge Gaps
- **791 isolated node(s):** `graphify-mcp`, `iaerp-backend`, `$schema`, `typescript`, `oxc` (+786 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **33 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `SalesDocument`, `get_store`, `billing.py`, `crm_integrations.py`, `sign_xml`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Why does `SalesDocument` connect `SalesDocument` to `_setup_billing_masters`, `build_ride_pdf`, `get_store`, `handle_invoice_authorized`, `billing.py`, `Party`, `Receivable`, `handle_invoice_signed`, `Base`, `Movement`, `initial_data.py`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Why does `LineInput` connect `LineInput` to `SalesDocument`, `build_ride_pdf`, `billing.py`, `build_invoice_xml`, `Base`, `initial_data.py`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Are the 41 inferred relationships involving `Receivable` (e.g. with `Base` and `TimestampMixin`) actually correct?**
  _`Receivable` has 41 INFERRED edges - model-reasoned connections that need verification._
- **What connects `graphify-mcp`, `iaerp-backend`, `$schema` to the rest of the system?**
  _791 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `_setup_billing_masters` be split into smaller, more focused modules?**
  _Cohesion score 0.07847082494969819 - nodes in this community are weakly interconnected._
- **Should `App.tsx` be split into smaller, more focused modules?**
  _Cohesion score 0.04251469923111714 - nodes in this community are weakly interconnected._