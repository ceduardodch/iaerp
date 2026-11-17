import assert from 'node:assert/strict'
import test from 'node:test'
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fiscalDay, importIsDue } from '../../infra/sri-importer/schedule.mjs'
import { profileRoot, readServiceAccount } from '../sri_received_runtime.mjs'

test('server runs at 08:00 Ecuador and catches up after a restart', () => {
  assert.equal(importIsDue('2026-11-16', new Date('2026-11-17T12:59:59Z')), false)
  assert.equal(importIsDue('2026-11-16', new Date('2026-11-17T13:00:00Z')), true)
  assert.equal(importIsDue('2026-11-16', new Date('2026-11-17T20:00:00Z')), true)
  assert.equal(importIsDue('2026-11-17', new Date('2026-11-17T20:00:00Z')), false)
  assert.equal(fiscalDay(new Date('2026-11-18T02:00:00Z')), '2026-11-17')
})

test('server credentials require private file permissions and the selected company', () => {
  const directory = mkdtempSync(join(tmpdir(), 'iaerp-sri-account-test-'))
  const path = join(directory, 'accounts.json')
  const previous = process.env.IAERP_SRI_ACCOUNTS_FILE
  try {
    writeFileSync(path, JSON.stringify({
      btob: { clientId: 'fixture-account', clientSecret: 'synthetic-test-value' }, // pragma: allowlist secret -- synthetic fixture
    }), { mode: 0o600 })
    process.env.IAERP_SRI_ACCOUNTS_FILE = path
    assert.equal(readServiceAccount({ id: 'btob' }).clientId, 'fixture-account')
    assert.throws(() => readServiceAccount({ id: 'other' }), /CONFIGURATION_MISSING/)
    chmodSync(path, 0o644)
    assert.throws(() => readServiceAccount({ id: 'btob' }), /PERMISSIONS_INVALID/)
  } finally {
    if (previous === undefined) delete process.env.IAERP_SRI_ACCOUNTS_FILE
    else process.env.IAERP_SRI_ACCOUNTS_FILE = previous
    rmSync(directory, { recursive: true })
  }
})

test('server profile root is explicit and keeps Mac compatibility', () => {
  assert.equal(profileRoot({ IAERP_SRI_PROFILE_ROOT: '/data/profiles' }, 'linux'), '/data/profiles')
  assert.match(profileRoot({}, 'linux'), /\.local\/share\/iaerp\/sri-profiles$/)
  assert.match(profileRoot({}, 'darwin'), /Library\/Application Support\/IAERP$/)
})
