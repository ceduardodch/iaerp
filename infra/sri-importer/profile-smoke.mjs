// Synthetic acceptance data only; never connects to SRI or IAERP.
import assert from 'node:assert/strict'
import { existsSync, lstatSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from '../../frontend/node_modules/playwright/index.mjs'
import { SRI_RECEIVED_COMPANIES } from '../../scripts/sri_received_companies.mjs'
import { profileRoot } from '../../scripts/sri_received_runtime.mjs'

const mode = process.argv[2]
assert.ok(['seed', 'assert', 'stale'].includes(mode))
for (const company of SRI_RECEIVED_COMPANIES) {
  const profile = join(profileRoot(), company.browserProfile)
  if (mode === 'stale') {
    for (const name of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
      assert.equal(lstatSync(join(profile, name)).isSymbolicLink(), true)
    }
    continue
  }
  const context = await chromium.launchPersistentContext(profile, {
    headless: true, chromiumSandbox: true,
  })
  try {
    const sentinel = join(profile, 'synthetic-restart-sentinel')
    if (mode === 'seed') {
      writeFileSync(sentinel, 'synthetic-profile-preserved', { mode: 0o600 })
      await context.addCookies([{
        name: 'synthetic_session', value: 'synthetic-persisted-session', // pragma: allowlist secret -- synthetic fixture
        domain: 'restart-check.invalid', path: '/', httpOnly: true,
        expires: Math.floor(Date.now() / 1000) + 86400,
      }])
    } else {
      assert.equal(readFileSync(sentinel, 'utf8'), 'synthetic-profile-preserved')
      assert.equal(existsSync(join(profile, 'Default', 'Cookies')), true)
      const cookies = await context.cookies('http://restart-check.invalid/')
      assert.ok(cookies.some((cookie) => cookie.name === 'synthetic_session'
        && cookie.value === 'synthetic-persisted-session'))
    }
  } finally { await context.close() }
}
process.stdout.write(`SRI_RESTART_SMOKE_${mode.toUpperCase()}_4_PROFILES_OK\n`)
