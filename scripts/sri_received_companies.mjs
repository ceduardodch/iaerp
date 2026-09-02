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
  Object.freeze({
    id: "lexcode",
    label: "LEXCODE AUDIT S.A.S.",
    sriKeychainService: "IAERP SRI Portal LEXCODE",
    sriUsernameAccount: "ruc",
    iaerpKeychainService: "IAERP SRI Daily Import LEXCODE",
    browserProfile: "sri-browser-profile-lexcode",
  }),
  Object.freeze({
    id: "ana-karina",
    label: "ANA KARINA DIAZ CHAVEZ",
    sriKeychainService: "IAERP SRI Portal ANA KARINA",
    sriUsernameAccount: "ruc",
    iaerpKeychainService: "IAERP SRI Daily Import ANA KARINA",
    browserProfile: "sri-browser-profile-ana-karina",
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
    throw new Error(
      `USAGE: --all | --company <${SRI_RECEIVED_COMPANIES.map((item) => item.id).join("|")}>`,
    );
  }

  const company = SRI_RECEIVED_COMPANIES.find((item) => item.id === requested);
  if (!company) {
    throw new Error(`UNKNOWN_COMPANY_${requested}`);
  }
  return [company];
}
