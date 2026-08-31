export const SRI_RECEIVED_COMPANIES = Object.freeze([
  Object.freeze({
    id: "data-clip",
    label: "DATA-CLIP",
    sriKeychainService: "IAERP SRI Portal",
    sriUsernameAccount: "ruc",
    iaerpKeychainService: "IAERP SRI Daily Import",
    browserProfile: "sri-browser-profile",
  }),
  Object.freeze({
    id: "btob",
    label: "BTOB SAS",
    sriKeychainService: "IAERP SRI Portal BTOB",
    sriUsernameAccount: "ruc",
    iaerpKeychainService: "IAERP SRI Daily Import BTOB",
    browserProfile: "sri-browser-profile-btob",
  }),
]);

export function selectSriReceivedCompanies(args = []) {
  if (args.length === 0) {
    return [SRI_RECEIVED_COMPANIES[0]];
  }
  if (args.length === 1 && args[0] === "--all") {
    return [...SRI_RECEIVED_COMPANIES];
  }

  let requested = null;
  if (args.length === 1 && args[0].startsWith("--company=")) {
    requested = args[0].slice("--company=".length);
  } else if (args.length === 2 && args[0] === "--company") {
    requested = args[1];
  }
  if (!requested) {
    throw new Error("USAGE: --all | --company <data-clip|btob>");
  }

  const company = SRI_RECEIVED_COMPANIES.find((item) => item.id === requested);
  if (!company) {
    throw new Error(`UNKNOWN_COMPANY_${requested}`);
  }
  return [company];
}
