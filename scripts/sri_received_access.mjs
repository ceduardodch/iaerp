export function parseSriReceivedMode(args) {
  const modes = args.filter((arg) => arg === "--check-access" || arg === "--download-only");
  const prompts = args.filter((arg) => arg === "--manual-captcha");
  const sessions = args.filter((arg) => arg === "--existing-session");
  if (modes.length > 1 || prompts.length > 1 || sessions.length > 1 ||
      (prompts.length && modes[0] === "--check-access")) {
    throw new Error("USAGE: [--check-access | --download-only] [--existing-session] [--manual-captcha] --all | --company <company>");
  }
  return {
    companyArgs: args.filter((arg) => !modes.includes(arg) && !prompts.includes(arg) && !sessions.includes(arg)),
    mode: modes[0] ?? null,
    manualCaptcha: prompts.length === 1,
    existingSession: sessions.length === 1,
  };
}

export function isOfficialSriUrl(value) {
  const url = new URL(value);
  return url.protocol === "https:" && url.hostname.endsWith(".sri.gob.ec");
}

export function isSriReceivedModuleUrl(value) {
  const url = new URL(value);
  return isOfficialSriUrl(url) && url.pathname.includes("comprobantes-electronicos-internet");
}

export function safeSriErrorCode(error) {
  const code = error instanceof Error ? error.message : "";
  return /^(?:SRI_|IAERP_|KEYCHAIN_)[A-Z0-9_]+(?:_[a-z-]+)?$/.test(code)
    ? code
    : "CHECK_FAILED";
}
