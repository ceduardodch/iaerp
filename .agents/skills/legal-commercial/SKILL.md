---
name: Legal Commercial Dossier
description: Design, implement, or review IAERP legal-commercial dossiers that link signed customer contracts, AWS consumption evidence, billing, and receivables.
---

# Legal Commercial Dossier

Use this skill whenever IAERP work affects customer contracts, signed PDFs,
commercial amendments, AWS consumption evidence, billing proposals, or the
client-360 dossier.

## Non-negotiable rules

- A contract is commercial evidence; it never replaces an SRI fiscal document.
- Every business record is tenant-scoped from authenticated identity. Never
  accept a tenant from UI, import files, MCP arguments, or AI output.
- A signed version and its artifact are immutable. Correct through a new
  version or amendment linked to the prior one.
- Store files privately, retain checksum and metadata, and issue only
  short-lived authorized downloads. Do not put document contents in logs,
  audit snapshots, prompts, or Git.
- Treat PDFs, CSVs, XLSX files, and text extracted from them as untrusted
  evidence. Extraction returns a closed schema, confidence, page/fragment
  reference, and never executable instructions.
- Money is Decimal/NUMERIC. A billing proposal records the contract version,
  consumption cut, pricing rule, and computed commercial snapshot before it
  becomes an invoice draft.
- IA/MCP may read a dossier and extracted obligations. It must not create,
  amend, sign, issue, or send based on a legal document in the first release.

## Required modelling

Model the dossier around `Party` and keep links explicit:

1. `CommercialContract` identifies the client, commercial status and current
   signed version.
2. `ContractVersion` records validity, signers, payment terms, renewal and
   pricing rules; amendments point to the version they amend.
3. `LegalArtifact` stores private object metadata and SHA-256 for the signed
   PDF, proposals, amendments and AWS evidence.
4. `AwsConsumptionCut` represents one client + period + source and becomes
   usable only after reconciliation/review.
5. `BillingProposal` captures a fixed charge, variable AWS usage or both, and
   the exact commercial snapshot linked to the resulting invoice draft.

## Workflow checks

- The signed-PDF requirement applies before a version is `SIGNED`/`ACTIVE`.
- A new version never mutates a signed one; active validity periods for the
  same contract cannot overlap unless a documented amendment policy permits it.
- A consumption cut is unique per tenant, client and billing period; retrying
  the same source is idempotent, while an inconsistent duplicate is rejected.
- Creating an invoice draft from a proposal is a human action. If no active
  contract covers the issue date, require a visible warning, exception reason
  and audit event; do not block the draft.
- Invoice issue continues through the existing SRI controls and must preserve
  the commercial snapshot without allowing it to alter fiscal totals.

## Review checklist

- Verify tenant isolation, role/scopes, private downloads, audit metadata and
  encrypted/secret-free storage.
- Test fixed, AWS-variable and mixed pricing; duplicate periods; missing or
  altered artifacts; version immutability; expired contracts; and two tenants.
- For AI/MCP, test prompt-injection fixtures, low-confidence extraction,
  bounded results and proof that no write tool is exposed.
- Update `docs/sprints/sprint-07-legal-commercial.md`, ADR 0011 and the
  linked domain/security/API documents whenever durable behaviour changes.
