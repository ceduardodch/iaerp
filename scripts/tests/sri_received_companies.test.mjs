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

test("selects all companies explicitly", () => {
  assert.deepEqual(
    selectSriReceivedCompanies(["--all"]).map((company) => company.id),
    ["data-clip", "btob", "lexcode"],
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
  for (const field of [
    "id",
    "sriKeychainService",
    "iaerpKeychainService",
    "browserProfile",
  ]) {
    const values = SRI_RECEIVED_COMPANIES.map((company) => company[field]);
    assert.equal(new Set(values).size, values.length, `${field} must be globally unique`);
  }
  for (const company of SRI_RECEIVED_COMPANIES) {
    assert.equal(company.sriUsernameAccount, "ruc");
  }
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
