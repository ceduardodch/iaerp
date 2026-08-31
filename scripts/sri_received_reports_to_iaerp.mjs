#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import { selectSriReceivedCompanies } from "./sri_received_companies.mjs";

const SRI_RECEIVED_URL =
  "https://srienlinea.sri.gob.ec/tuportal-internet/" +
  "accederAplicacion.jspa?redireccion=57&idGrupo=55";
const IAERP_URL = "https://iaerp.b2b.com.ec";
const TOKEN_URL =
  "https://iaerp-auth.b2b.com.ec/realms/iaerp/protocol/openid-connect/token";
const PROFILE_ROOT = join(homedir(), "Library", "Application Support", "IAERP");

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

function readKeychain(service, account) {
  return execFileSync(
    "/usr/bin/security",
    ["find-generic-password", "-s", service, "-a", account, "-w"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  ).trim();
}

function readCompanyKeychain(service, account, companyId) {
  try {
    return readKeychain(service, account);
  } catch {
    throw new Error(`KEYCHAIN_CONFIGURATION_MISSING_${companyId}`);
  }
}

function fiscalPeriodForYesterday() {
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
  if (!page.url().includes("/auth/realms/Internet/")) return;

  const rucField = page.locator('input[name="usuario"]');
  const passwordField = page.locator('input[name="password"]');
  await rucField.waitFor({ state: "visible", timeout: 30_000 });
  await passwordField.waitFor({ state: "visible", timeout: 30_000 });
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

async function openReceivedReports(page, credentials) {
  await page.goto(SRI_RECEIVED_URL, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  await loginIfNeeded(page, credentials);
  await page.waitForURL((url) =>
    url.href.includes("comprobantes-electronicos-internet"), {
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
    throw new Error("El SRI no conservó el periodo mensual solicitado.");
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

async function queryAndDownload(page, runtimeDir, slug, label) {
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

  const bodyText = await page.locator("body").innerText();
  if (/captcha/i.test(bodyText) && /(error|incorrect|inválid|invalido)/i.test(bodyText)) {
    throw new Error("SRI_CAPTCHA_REQUIRED");
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

  if (statSync(destination).size === 0) {
    return null;
  }
  const nonEmptyLines = readFileSync(destination, "utf8")
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0);
  return nonEmptyLines.length > 1 ? destination : null;
}

async function getIaerpToken(company) {
  let clientId = readCompanyKeychain(
    company.iaerpKeychainService,
    "client_id",
    company.id,
  );
  let clientSecret = readCompanyKeychain(
    company.iaerpKeychainService,
    "client_secret",
    company.id,
  );
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

async function runCompany(company, period) {
  const runtimeDir = mkdtempSync(join(tmpdir(), `iaerp-sri-${company.id}-`));
  chmodSync(runtimeDir, 0o700);
  let context;
  let stage = "credentials";
  let sriCredentials = { ruc: "", password: "" };

  try {
    sriCredentials = {
      ruc: readCompanyKeychain(
        company.sriKeychainService,
        company.sriUsernameAccount,
        company.id,
      ),
      password: readCompanyKeychain(company.sriKeychainService, "password", company.id),
    };
    stage = "browser";
    context = await chromium.launchPersistentContext(
      join(PROFILE_ROOT, company.browserProfile),
      {
        channel: "chrome",
        headless: false,
        locale: "es-EC",
        timezoneId: "America/Guayaquil",
        viewport: { width: 1366, height: 900 },
        acceptDownloads: true,
      },
    );
    const page = context.pages()[0] ?? (await context.newPage());
    const downloaded = [];

    for (const [slug, label] of REPORT_TYPES) {
      stage = `sri-${slug}`;
      await openReceivedReports(page, sriCredentials);
      await selectPeriod(page, period.year, period.month);
      const filePath = await queryAndDownload(page, runtimeDir, slug, label);
      if (filePath) downloaded.push({ slug, filePath });
    }

    sriCredentials = { ruc: "", password: "" };
    if (downloaded.length === 0) {
      throw new Error("SRI_NO_REPORTS_WITH_ROWS");
    }

    stage = "iaerp-token";
    const token = await getIaerpToken(company);
    const evidence = [];
    for (const report of downloaded) {
      stage = `iaerp-evidence-${report.slug}`;
      evidence.push(await uploadEvidence(token, report.filePath, period, report.slug));
    }
    stage = "iaerp-process";
    const result = await processReports(token, evidence, period);

    return {
      company: company.label,
      period: `${period.year}-${String(period.month).padStart(2, "0")}`,
      reportCount: downloaded.length,
      evidenceCount: evidence.length,
      listedRows: result.listedRows,
      documentTypes: result.documentTypes,
      created: result.created,
      updated: result.updated,
      skipped: result.skipped,
      preliminary: result.preliminary,
      recoveryStatus: result.recoveryJob?.status ?? null,
    };
  } catch (error) {
    throw new Error(`STAGE_${stage}: ${error.message}`);
  } finally {
    sriCredentials = { ruc: "", password: "" };
    if (context) await context.close();
    rmSync(runtimeDir, { recursive: true, force: true });
  }
}

let companies;
try {
  companies = selectSriReceivedCompanies(process.argv.slice(2));
} catch (error) {
  process.stderr.write(`SRI_RECEIVED_FAILED: ${error.message}\n`);
  process.exit(1);
}

const period = fiscalPeriodForYesterday();
let failed = false;
for (const company of companies) {
  try {
    process.stdout.write(`${JSON.stringify(await runCompany(company, period))}\n`);
  } catch (error) {
    process.stderr.write(`SRI_RECEIVED_FAILED_${company.id}: ${error.message}\n`);
    failed = true;
  }
}
if (failed) process.exitCode = 1;
