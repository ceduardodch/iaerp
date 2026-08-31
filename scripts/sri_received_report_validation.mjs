import { readFileSync } from "node:fs";

function isAsciiDigits(value, length) {
  return value.length === length && /^[0-9]+$/.test(value);
}

export function isValidNaturalPersonRuc(value) {
  if (!isAsciiDigits(value, 13) || !value.endsWith("001")) return false;
  const cedula = value.slice(0, 10);
  if (Number(cedula[2]) > 5) return false;
  let total = 0;
  for (let index = 0; index < 9; index += 1) {
    const digit = Number(cedula[index]);
    const product = digit * (index % 2 === 0 ? 2 : 1);
    total += product > 9 ? product - 9 : product;
  }
  return (10 - (total % 10)) % 10 === Number(cedula[9]);
}

export function receiverMatchesExpectedRuc(receiver, expectedRuc) {
  if (receiver === expectedRuc) return true;
  return isValidNaturalPersonRuc(expectedRuc) && receiver === expectedRuc.slice(0, 10);
}

export function validateReceivedReportBytes(bytes, expectedRuc) {
  const lines = bytes.toString("latin1").split(/\r?\n/).filter((line) => line.trim());
  if (lines.length < 2) throw new Error("SRI_REPORT_HAS_NO_ROWS");
  const headers = lines[0].split("\t").map((header) => header.trim());
  const receiverIndex = headers.indexOf("IDENTIFICACION_RECEPTOR");
  if (receiverIndex < 0) throw new Error("SRI_REPORT_RECEIVER_COLUMN_MISSING");

  for (const line of lines.slice(1)) {
    const receiver = (line.split("\t")[receiverIndex] ?? "").trim();
    if (!receiverMatchesExpectedRuc(receiver, expectedRuc)) {
      throw new Error("SRI_REPORT_RECEIVER_MISMATCH");
    }
  }
}

export function validateDownloadedReports(downloaded, expectedRuc) {
  // Valida el lote completo antes de que el ejecutor inicie la primera subida.
  for (const report of downloaded) {
    validateReceivedReportBytes(readFileSync(report.filePath), expectedRuc);
  }
}
