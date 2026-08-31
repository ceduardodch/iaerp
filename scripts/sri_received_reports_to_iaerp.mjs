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

const SRI_KEYCHAIN_SERVICE = "IAERP SRI Portal";
const IAERP_KEYCHAIN_SERVICE = "IAERP SRI Daily Import";
const SRI_RECEIVED_URL =
  "https://srienlinea.sri.gob.ec/tuportal-internet/" +
  "accederAplicacion.jspa?redireccion=57&idGrupo=55";
const IAERP_URL = "https://iaerp.b2b.com.ec";
const TOKEN_URL =
  "https://iaerp-auth.b2b.com.ec/realms/iaerp/protocol/openid-connect/token";
const PROFILE_DIR = join(
  homedir(),
  "Library",
  "Application Support",
  "IAERP",
  "sri-browser-profile",
);

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
  await locator.click();
  await locator.press("Meta+A");
  await locator.press("Backspace");
  await locator.pressSequentially(value, { delay: 45 });
}

async function loginIfNeeded(page, credentials) {
  if (!page.url().includes("/auth/realms/Internet/")) return;

  const rucField = page.locator('input[name="usuario"]');
  const passwordField = page.locator('input[name="password"]');
  await rucField.waitFor({ state: "visible", timeout: 30_000 });
  await passwordField.waitFor({ state: "visible", timeout: 30_000 });
  await typeLikeUser(rucField, credentials.ruc);
  await typeLikeUser(passwordField, credentials.password);

  await Promise.all([
    page.waitForURL((url) => !url.href.includes("/auth/realms/Internet/"), {
      timeout: 60_000,
    }),
    page.locator('input[name="login"]').click(),
  ]);
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

async function getIaerpToken() {
  let clientId = readKeychain(IAERP_KEYCHAIN_SERVICE, "client_id");
  let clientSecret = readKeychain(IAERP_KEYCHAIN_SERVICE, "client_secret");
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

const runtimeDir = mkdtempSync(join(tmpdir(), "iaerp-sri-received-"));
chmodSync(runtimeDir, 0o700);
const period = fiscalPeriodForYesterday();
let context;
let sriCredentials = { ruc: "", password: "" };

try {
  sriCredentials = {
    ruc: readKeychain(SRI_KEYCHAIN_SERVICE, "ruc"),
    password: readKeychain(SRI_KEYCHAIN_SERVICE, "password"),
  };
  context = await chromium.launchPersistentContext(PROFILE_DIR, {
    channel: "chrome",
    headless: false,
    locale: "es-EC",
    timezoneId: "America/Guayaquil",
    viewport: { width: 1366, height: 900 },
    acceptDownloads: true,
  });
  const page = context.pages()[0] ?? (await context.newPage());
  const downloaded = [];

  for (const [slug, label] of REPORT_TYPES) {
    await openReceivedReports(page, sriCredentials);
    await selectPeriod(page, period.year, period.month);
    const filePath = await queryAndDownload(page, runtimeDir, slug, label);
    if (filePath) downloaded.push({ slug, filePath });
  }

  sriCredentials = { ruc: "", password: "" };
  if (downloaded.length === 0) {
    throw new Error("SRI_NO_REPORTS_WITH_ROWS");
  }

  const token = await getIaerpToken();
  const evidence = [];
  for (const report of downloaded) {
    evidence.push(await uploadEvidence(token, report.filePath, period, report.slug));
  }
  const result = await processReports(token, evidence, period);

  process.stdout.write(`${JSON.stringify({
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
  })}\n`);
} catch (error) {
  process.stderr.write(`SRI_RECEIVED_FAILED: ${error.message}\n`);
  process.exitCode = 1;
} finally {
  sriCredentials = { ruc: "", password: "" };
  if (context) await context.close();
  rmSync(runtimeDir, { recursive: true, force: true });
}
