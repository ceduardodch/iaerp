import assert from "node:assert/strict";
import test from "node:test";

import { isOfficialSriUrl, isSriReceivedModuleUrl, parseSriReceivedMode, safeSriErrorCode } from "../sri_received_access.mjs";

test("keeps access and download checks separate from normal imports", () => {
  assert.deepEqual(parseSriReceivedMode(["--company=btob", "--download-only"]), {
    companyArgs: ["--company=btob"], mode: "--download-only", manualCaptcha: false, existingSession: false,
  });
  assert.deepEqual(parseSriReceivedMode(["--check-access", "--company", "btob"]), {
    companyArgs: ["--company", "btob"], mode: "--check-access", manualCaptcha: false, existingSession: false,
  });
  assert.equal(parseSriReceivedMode(["--download-only", "--manual-captcha"]).manualCaptcha, true);
  assert.deepEqual(parseSriReceivedMode(["--all", "--existing-session"]), {
    companyArgs: ["--all"], mode: null, manualCaptcha: false, existingSession: true,
  });
  assert.equal(parseSriReceivedMode(["--all"]).mode, null);
  assert.throws(() => parseSriReceivedMode(["--download-only", "--check-access"]), /USAGE/);
  assert.throws(() => parseSriReceivedMode(["--check-access", "--check-access"]), /USAGE/);
  assert.throws(() => parseSriReceivedMode(["--check-access", "--manual-captcha"]), /USAGE/);
});

test("only accepts HTTPS on a host belonging to SRI", () => {
  assert.equal(isOfficialSriUrl("https://srienlinea.sri.gob.ec/auth/realms/Internet/"), true);
  assert.equal(isOfficialSriUrl("http://srienlinea.sri.gob.ec/auth/realms/Internet/"), false);
  assert.equal(isOfficialSriUrl("https://sri.gob.ec.example.com/auth/realms/Internet/"), false);
  assert.equal(isOfficialSriUrl("https://sri.gob.ec@example.com/auth/realms/Internet/"), false);
  assert.equal(isSriReceivedModuleUrl("about:blank"), false);
  assert.equal(isSriReceivedModuleUrl("https://srienlinea.sri.gob.ec/comprobantes-electronicos-internet/"), true);
});

test("unknown browser errors cannot include a credential or URL in the summary", () => {
  assert.equal(safeSriErrorCode(new Error('locator.fill("example") failed')), "CHECK_FAILED");
  assert.equal(safeSriErrorCode(new Error("SRI_AUTHENTICATION_REJECTED")), "SRI_AUTHENTICATION_REJECTED");
});
