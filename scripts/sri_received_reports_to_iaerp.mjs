#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline/promises";

import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import {
  isOfficialSriUrl,
  isSriReceivedModuleUrl,
  parseSriReceivedMode,
  safeSriErrorCode,
} from "./sri_received_access.mjs";
import { selectSriReceivedCompanies } from "./sri_received_companies.mjs";
import { validateDownloadedReports } from "./sri_received_report_validation.mjs";
import { profileRoot, readServiceAccount } from "./sri_received_runtime.mjs";

const SRI_RECEIVED_URL =
  "https://srienlinea.sri.gob.ec/tuportal-internet/" +
  "accederAplicacion.jspa?redireccion=57&idGrupo=55";
const IAERP_URL = "https://iaerp.b2b.com.ec";
const TOKEN_URL =
  "https://iaerp-auth.b2b.com.ec/realms/iaerp/protocol/openid-connect/token";
const PROFILE_ROOT = profileRoot();
const MONTH_NAMES = [
  "Enero",
  "Febrero",
  "Marzo",
  "Abril",
  "Mayo",
  "Junio",
  "Julio",
  "Agosto",
  "Septiembre",
  "Octubre",
  "Noviembre",
  "Diciembre",
];

const REPORT_TYPES = [
  ["factura", "Factura"],
  ["liquidacion_compra", "Liquidación de compra de bienes y prestación de servicios"],
  ["nota_credito", "Notas de Crédito"],
  ["nota_debito", "Notas de Débito"],
  ["retencion", "Comprobante de Retención"],
];

export function fiscalPeriodForYesterday() {
  const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Guayaquil",
    year: "numeric",
    month: "2-digit",
  }).formatToParts(yesterday);
  return {
    year: Number(parts.find((part) => part.type === "year").value),
    month: Number(parts.find((part) => part.type === "month").value),
  };
}

async function typeLikeUser(locator, value) {
  await locator.fill("");
  await locator.fill(value);
  if (await locator.inputValue() !== value) {
    throw new Error("SRI_CREDENTIAL_FIELD_MISMATCH");
  }
}

async function loginIfNeeded(page, credentials) {
  const loginUrl = new URL(page.url());
  if (!isOfficialSriUrl(loginUrl)) throw new Error("SRI_UNEXPECTED_ORIGIN");
  if (!loginUrl.pathname.includes("/auth/realms/Internet/")) return;

  const rucField = page.locator('input[name="usuario"]');
  const passwordField = page.locator('input[name="password"]');
  await rucField.waitFor({ state: "visible", timeout: 30_000 });
  await passwordField.waitFor({ state: "visible", timeout: 30_000 });
  if (page.url() !== loginUrl.href) throw new Error("SRI_LOGIN_PAGE_CHANGED");
  await typeLikeUser(rucField, credentials.ruc);
  await typeLikeUser(passwordField, credentials.password);

  // Chrome can restore a saved login after the first field changes. Reassert
  // both values immediately before submitting and verify them without logging.
  await typeLikeUser(rucField, credentials.ruc);
  await typeLikeUser(passwordField, credentials.password);

  await page.locator('input[name="login"]').click();
  try {
    await page.waitForURL((url) => !url.href.includes("/auth/realms/Internet/"), {
      timeout: 60_000,
    });
  } catch {
    const bodyText = await page.locator("body").innerText();
    if (/captcha/i.test(bodyText)) {
      throw new Error("SRI_CAPTCHA_REQUIRED");
    }
    if (/(código|codigo).*(verificación|verificacion)|segundo factor|token/i.test(bodyText)) {
      throw new Error("SRI_MFA_REQUIRED");
    }
    if (
      /(usuario|nombre de usuario|contraseña|clave).*(inválid|invalid|incorrect|no válid)/i
        .test(bodyText)
    ) {
      throw new Error("SRI_AUTHENTICATION_REJECTED");
    }
    throw new Error("SRI_LOGIN_NOT_COMPLETED");
  }
}

async function openReceivedReports(page, credentials, existingSession) {
  if (!isSriReceivedModuleUrl(page.url())) {
    await page.goto(SRI_RECEIVED_URL, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
  }
  if (existingSession && new URL(page.url()).pathname.includes("/auth/realms/Internet/")) {
    throw new Error("SRI_SESSION_REQUIRED");
  }
  await loginIfNeeded(page, credentials);
  await page.waitForURL(isSriReceivedModuleUrl, {
    timeout: 60_000,
  });
  await page.locator("#frmPrincipal\\:ano").waitFor({
    state: "visible",
    timeout: 30_000,
  });
}

async function selectPeriod(page, year, month) {
  await page.locator("#frmPrincipal\\:ano").selectOption(String(year));
  await page.locator("#frmPrincipal\\:mes").selectOption({
    label: MONTH_NAMES[month - 1],
  });
  await page.waitForTimeout(1_200);
  await page.locator("#frmPrincipal\\:dia").selectOption({ label: "Todos" });

  const selected = await Promise.all([
    page.locator("#frmPrincipal\\:ano").inputValue(),
    page.locator("#frmPrincipal\\:mes option:checked").innerText(),
    page.locator("#frmPrincipal\\:dia option:checked").innerText(),
  ]);
  if (
    selected[0] !== String(year) ||
    selected[1].trim() !== MONTH_NAMES[month - 1] ||
    selected[2].trim() !== "Todos"
  ) {
    throw new Error("SRI_MONTH_SELECTION_CHANGED");
  }
}

async function firstVisible(locators, label) {
  for (const locator of locators) {
    if ((await locator.count()) > 0 && await locator.first().isVisible()) {
      return locator.first();
    }
  }
  throw new Error(`SRI_CONTROL_NOT_FOUND_${label}`);
}

async function queryAndDownload(page, runtimeDir, slug, label, manualCaptcha, captchaHandler) {
  await page.locator("#frmPrincipal\\:cmbTipoComprobante").selectOption({ label });
  await page.waitForTimeout(500);
  const queryButton = await firstVisible([
    page.locator("#frmPrincipal\\:btnBuscar"),
    page.getByRole("button", { name: "Consultar", exact: true }),
    page.locator('input[value="Consultar"]'),
    page.getByText("Consultar", { exact: true }),
  ], "CONSULTAR");
  await queryButton.click();
  await page.waitForTimeout(9_000);

  const captchaRejected = (text) => /captcha/i.test(text) && /(error|incorrect|inválid|invalido)/i.test(text);
  let bodyText = await page.locator("body").innerText();
  if (captchaRejected(bodyText)) {
    if (captchaHandler) {
      await captchaHandler(page, slug);
    } else {
      if (!manualCaptcha) throw new Error("SRI_CAPTCHA_REQUIRED");
      const terminal = createInterface({ input: process.stdin, output: process.stderr });
      try {
        await terminal.question(
          `SRI_CAPTCHA_MANUAL_${slug}: resuelve el CAPTCHA y pulsa Consultar en Chrome. Cuando aparezca el resultado, presiona Enter aquí.\n`,
          { signal: AbortSignal.timeout(10 * 60_000) },
        );
      } finally {
        terminal.close();
      }
    }
    bodyText = await page.locator("body").innerText();
    if (captchaRejected(bodyText)) throw new Error("SRI_CAPTCHA_REQUIRED");
  }
  if (/No existen datos para los parámetros ingresados/i.test(bodyText)) {
    return null;
  }

  const downloadLink = page.getByText("Descargar reporte", { exact: true });
  await downloadLink.waitFor({ state: "visible", timeout: 15_000 });
  const downloadPromise = page.waitForEvent("download", { timeout: 45_000 });
  await downloadLink.click();
  const download = await downloadPromise;
  const destination = join(runtimeDir, `${slug}.txt`);
  await download.saveAs(destination);

  if (statSync(destination).size === 0) throw new Error("SRI_DOWNLOADED_REPORT_EMPTY");
  return destination;
}

async function getIaerpToken(company) {
  let { clientId, clientSecret } = readServiceAccount(company);
  const body = new URLSearchParams({
    grant_type: "client_credentials",
    client_id: clientId,
    client_secret: clientSecret,
  });
  clientId = "";
  clientSecret = "";

  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) {
    throw new Error(`IAERP_TOKEN_FAILED_${response.status}`);
  }
  return (await response.json()).access_token;
}

async function uploadEvidence(token, filePath, period, slug) {
  const bytes = readFileSync(filePath);
  const digest = createHash("sha256").update(bytes).digest("hex");
  const form = new FormData();
  form.set("origin", "PORTAL_SRI");
  form.set("file", new Blob([bytes], { type: "text/plain" }), `${slug}.txt`);
  const response = await fetch(`${IAERP_URL}/api/v1/tax/evidence`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Idempotency-Key": `sri-${period.year}-${period.month}-${slug}-${digest.slice(0, 24)}`,
    },
    body: form,
  });
  if (!response.ok) {
    throw new Error(`IAERP_EVIDENCE_FAILED_${slug}_${response.status}`);
  }
  const payload = await response.json();
  return { id: payload.id, digest };
}

async function preflightTenant(token, expectedRuc) {
  const response = await fetch(`${IAERP_URL}/api/v1/tax/received-reports/preflight`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ expectedRuc }),
  });
  if (!response.ok) {
    throw new Error(`IAERP_TENANT_PREFLIGHT_FAILED_${response.status}`);
  }
}

async function getSriPortalCredentials(token) {
  const response = await fetch(`${IAERP_URL}/api/v1/tax/automation/sri-portal-credentials`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(`IAERP_SRI_CREDENTIALS_FAILED_${response.status}`);
  }
  const payload = await response.json();
  if (!/^\d{13}$/.test(payload.ruc) || typeof payload.password !== "string" || !payload.password) { // pragma: allowlist secret
    throw new Error("IAERP_SRI_CREDENTIALS_INVALID");
  }
  return { ruc: payload.ruc, password: payload.password };
}

async function processReports(token, evidence, period) {
  const setDigest = createHash("sha256")
    .update(evidence.map((item) => item.digest).sort().join(":"))
    .digest("hex");
  const response = await fetch(`${IAERP_URL}/api/v1/tax/received-reports/process`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": `sri-process-${period.year}-${period.month}-${setDigest.slice(0, 24)}`,
    },
    body: JSON.stringify({
      evidenceIds: evidence.map((item) => item.id),
      reportYear: period.year,
      reportMonth: period.month,
    }),
  });
  if (!response.ok) {
    throw new Error(`IAERP_PROCESS_FAILED_${response.status}`);
  }
  return response.json();
}

function summarizeImport(company, period, reportCount, result = {}) {
  return {
    company: company.label,
    period: `${period.year}-${String(period.month).padStart(2, "0")}`,
    reportCount,
    evidenceCount: reportCount,
    listedRows: result.listedRows ?? 0,
    documentTypes: result.documentTypes ?? {},
    created: result.created ?? 0,
    updated: result.updated ?? 0,
    skipped: result.skipped ?? 0,
    preliminary: result.preliminary ?? 0,
    recoveryStatus: result.recoveryJob?.status ?? null,
  };
}

export async function runCompany(company, period, {
  mode, manualCaptcha, existingSession, browserContext, captchaHandler,
}) {
  const runtimeDir = mkdtempSync(join(tmpdir(), `iaerp-sri-${company.id}-`));
  chmodSync(runtimeDir, 0o700);
  let context;
  let stage = "credentials";
  let sriCredentials = { ruc: "", password: "" };
  let token = "";

  try {
    stage = "iaerp-token";
    token = await getIaerpToken(company);
    stage = "iaerp-sri-credentials";
    sriCredentials = await getSriPortalCredentials(token);
    stage = "iaerp-preflight";
    await preflightTenant(token, sriCredentials.ruc);
    stage = "browser";
    const profileDir = join(PROFILE_ROOT, company.browserProfile);
    if (existingSession && !existsSync(profileDir)) throw new Error("SRI_PROFILE_REQUIRED");
    mkdirSync(profileDir, { recursive: true, mode: 0o700 });
    context = browserContext ?? await chromium.launchPersistentContext(
      profileDir,
      {
        channel: "chrome",
        headless: false,
        locale: "es-EC",
        timezoneId: "America/Guayaquil",
        viewport: { width: 1366, height: 900 },
        acceptDownloads: true,
      },
    );
    const pages = context.pages();
    const page = pages.find((candidate) => isSriReceivedModuleUrl(candidate.url()))
      ?? pages[0] ?? (await context.newPage());
    const downloaded = [];

    // Enter the module once. Reopening the SRI launcher for each document type
    // can close the active page when it reuses an authenticated session.
    stage = "sri-login";
    await openReceivedReports(page, sriCredentials, existingSession);
    if (mode === "--check-access") return { profile: company.id, accessStatus: "SRI_ACCESS_VERIFIED" };

    for (const [slug, label] of REPORT_TYPES) {
      stage = `sri-${slug}`;
      await selectPeriod(page, period.year, period.month);
      const filePath = await queryAndDownload(page, runtimeDir, slug, label, manualCaptcha, captchaHandler);
      if (filePath) downloaded.push({ slug, filePath });
    }

    stage = "sri-report-tenant-validation";
    const listedRows = validateDownloadedReports(downloaded, sriCredentials.ruc);
    sriCredentials = { ruc: "", password: "" };
    if (mode === "--download-only") {
      return {
        profile: company.id,
        period: `${period.year}-${String(period.month).padStart(2, "0")}`,
        reportCount: downloaded.length,
        listedRows,
        reportTypes: downloaded.map((report) => report.slug),
      };
    }
    if (downloaded.length === 0) return summarizeImport(company, period, 0);
    const evidence = [];
    for (const report of downloaded) {
      stage = `iaerp-evidence-${report.slug}`;
      evidence.push(await uploadEvidence(token, report.filePath, period, report.slug));
    }
    stage = "iaerp-process";
    const result = await processReports(token, evidence, period);

    return summarizeImport(company, period, evidence.length, result);
  } catch (error) {
    throw new Error(`STAGE_${stage}: ${safeSriErrorCode(error)}`);
  } finally {
    sriCredentials = { ruc: "", password: "" };
    token = "";
    try {
      if (context && !browserContext) await context.close();
    } catch {
      throw new Error("STAGE_browser-cleanup: CHECK_FAILED");
    } finally {
      rmSync(runtimeDir, { recursive: true, force: true });
    }
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  let companies;
  let verification;
  try {
    verification = parseSriReceivedMode(process.argv.slice(2));
    companies = selectSriReceivedCompanies(verification.companyArgs);
  } catch (error) {
    process.stderr.write(`SRI_RECEIVED_FAILED: ${error.message}\n`);
    process.exit(1);
  }
  const period = fiscalPeriodForYesterday();
  let failed = false;
  for (const company of companies) {
    try {
      process.stdout.write(`${JSON.stringify(await runCompany(company, period, verification))}\n`);
    } catch (error) {
      process.stderr.write(`SRI_RECEIVED_FAILED_${company.id}: ${error.message}\n`);
      failed = true;
    }
  }
  if (failed) process.exitCode = 1;
}
