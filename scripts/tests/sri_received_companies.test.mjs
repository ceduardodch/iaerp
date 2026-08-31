import assert from "node:assert/strict";
import test from "node:test";

import {
  SRI_RECEIVED_COMPANIES,
  selectSriReceivedCompanies,
} from "../sri_received_companies.mjs";

test("keeps DATA-CLIP as the safe default", () => {
  assert.deepEqual(
    selectSriReceivedCompanies().map((company) => company.id),
    ["data-clip"],
  );
});

test("selects both companies explicitly", () => {
  assert.deepEqual(
    selectSriReceivedCompanies(["--all"]).map((company) => company.id),
    ["data-clip", "btob"],
  );
});

test("selects one company by id", () => {
  assert.equal(selectSriReceivedCompanies(["--company=btob"])[0].label, "BTOB SAS");
  assert.equal(
    selectSriReceivedCompanies(["--company", "data-clip"])[0].id,
    "data-clip",
  );
});

test("uses separate secret services and browser profiles", () => {
  const [dataClip, btob] = SRI_RECEIVED_COMPANIES;
  assert.notEqual(dataClip.sriKeychainService, btob.sriKeychainService);
  assert.notEqual(dataClip.iaerpKeychainService, btob.iaerpKeychainService);
  assert.notEqual(dataClip.browserProfile, btob.browserProfile);
  assert.equal(dataClip.sriUsernameAccount, "ruc");
  assert.equal(btob.sriUsernameAccount, "ruc");
});

test("rejects unknown or ambiguous arguments", () => {
  assert.throws(
    () => selectSriReceivedCompanies(["--company=unknown"]),
    /UNKNOWN_COMPANY_unknown/,
  );
  assert.throws(
    () => selectSriReceivedCompanies(["--company"]),
    /USAGE/,
  );
  assert.throws(
    () => selectSriReceivedCompanies(["--company=btob", "unexpected"]),
    /USAGE/,
  );
});
