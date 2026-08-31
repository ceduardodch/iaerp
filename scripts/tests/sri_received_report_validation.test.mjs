import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  receiverMatchesExpectedRuc,
  validateDownloadedReports,
  validateReceivedReportBytes,
} from "../sri_received_report_validation.mjs";

function report(receiver) {
  return Buffer.from(
    "RUC_EMISOR\tIDENTIFICACION_RECEPTOR\tCLAVE_ACCESO\n" +
      `1790000000001\t${receiver}\t${"1".repeat(49)}\n`,
    "latin1",
  );
}

test("accepts exact tenant RUC and natural-person cedula homologation", () => {
  assert.equal(receiverMatchesExpectedRuc("1799999999001", "1799999999001"), true);
  assert.equal(receiverMatchesExpectedRuc("1712345675", "1712345675001"), true);
  assert.equal(receiverMatchesExpectedRuc("1799999999", "1799999999001"), false);
});

test("rejects a report downloaded from another persistent SRI session", () => {
  assert.throws(
    () => validateReceivedReportBytes(report("1799999999002"), "1799999999001"),
    /SRI_REPORT_RECEIVER_MISMATCH/,
  );
});

test("validates every report before the first upload", () => {
  const runtimeDir = mkdtempSync(join(tmpdir(), "iaerp-sri-validation-test-"));
  try {
    const matchingPath = join(runtimeDir, "matching.txt");
    const crossedPath = join(runtimeDir, "crossed.txt");
    writeFileSync(matchingPath, report("1799999999001"));
    writeFileSync(crossedPath, report("1799999999002"));
    let uploads = 0;

    assert.throws(() => {
      const downloaded = [
        { slug: "factura", filePath: matchingPath },
        { slug: "retencion", filePath: crossedPath },
      ];
      validateDownloadedReports(downloaded, "1799999999001");
      for (const _report of downloaded) uploads += 1;
    }, /SRI_REPORT_RECEIVER_MISMATCH/);
    assert.equal(uploads, 0);
  } finally {
    rmSync(runtimeDir, { recursive: true, force: true });
  }
});

test("rejects malformed or empty listings", () => {
  assert.throws(
    () => validateReceivedReportBytes(Buffer.from("CLAVE_ACCESO\nvalue\n"), "1799999999001"),
    /SRI_REPORT_RECEIVER_COLUMN_MISSING/,
  );
  assert.throws(
    () => validateReceivedReportBytes(Buffer.from("IDENTIFICACION_RECEPTOR\n"), "1799999999001"),
    /SRI_REPORT_HAS_NO_ROWS/,
  );
});

test("runCompany validates with the populated RUC before clearing and uploading", () => {
  const scriptPath = fileURLToPath(
    new URL("../sri_received_reports_to_iaerp.mjs", import.meta.url),
  );
  const source = readFileSync(scriptPath, "utf8");
  const runCompany = source.slice(source.indexOf("async function runCompany"));
  const validationIndex = runCompany.indexOf(
    "validateDownloadedReports(downloaded, sriCredentials.ruc);",
  );
  const clearIndex = runCompany.indexOf(
    'sriCredentials = { ruc: "", password: "" };',
    validationIndex,
  );
  const uploadIndex = runCompany.indexOf("uploadEvidence(", clearIndex);

  assert.ok(validationIndex >= 0);
  assert.ok(clearIndex > validationIndex);
  assert.ok(uploadIndex > clearIndex);
});
