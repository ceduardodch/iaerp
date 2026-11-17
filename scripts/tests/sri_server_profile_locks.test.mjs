import assert from 'node:assert/strict'
import { lstatSync, mkdirSync, mkdtempSync, readFileSync, readlinkSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { clearStaleProfileLocks } from '../../infra/sri-importer/profile-locks.mjs'

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'iaerp-profile-lock-'))
  const profile = join(root, 'btob')
  const procRoot = join(root, 'proc')
  mkdirSync(profile)
  mkdirSync(procRoot)
  mkdirSync(join(profile, 'Default'))
  writeFileSync(join(profile, 'Default', 'Cookies'), 'synthetic-cookie-database')
  writeFileSync(join(profile, 'Local State'), 'synthetic-state')
  writeFileSync(join(root, 'target'), 'keep-symlink-target')
  symlinkSync('old-container-331', join(profile, 'SingletonLock'))
  symlinkSync(join(root, 'target'), join(profile, 'SingletonSocket'))
  symlinkSync('synthetic-token', join(profile, 'SingletonCookie'))
  return { root, profile, procRoot, close: () => rmSync(root, { recursive: true, force: true }) }
}

function processFixture(item, argv, pid = '331') {
  mkdirSync(join(item.procRoot, pid))
  writeFileSync(join(item.procRoot, pid, 'cmdline'), argv.join('\0') + '\0')
}

test('foreign-host stale links are unlinked while Cookies, state, and targets survive', () => {
  const item = fixture()
  try {
    assert.deepEqual(clearStaleProfileLocks(item.profile, { procRoot: item.procRoot }), [
      'SingletonSocket', 'SingletonCookie', 'SingletonLock',
    ])
    assert.equal(readFileSync(join(item.profile, 'Default', 'Cookies'), 'utf8'), 'synthetic-cookie-database')
    assert.equal(readFileSync(join(item.profile, 'Local State'), 'utf8'), 'synthetic-state')
    assert.equal(readFileSync(join(item.root, 'target'), 'utf8'), 'keep-symlink-target')
  } finally { item.close() }
})

test('live same-container Chrome with the exact profile blocks all cleanup', () => {
  const item = fixture()
  try {
    processFixture(item, ['/opt/google/chrome', '--user-data-dir=' + realpathSync(item.profile)])
    assert.throws(() => clearStaleProfileLocks(item.profile, { host: 'old-container', procRoot: item.procRoot }), /SRI_PROFILE_IN_USE/)
    assert.equal(readlinkSync(join(item.profile, 'SingletonLock')), 'old-container-331')
    assert.equal(readlinkSync(join(item.profile, 'SingletonSocket')), join(item.root, 'target'))
  } finally { item.close() }
})

test('PID reuse with a different profile does not preserve a stale lock', () => {
  const item = fixture()
  try {
    processFixture(item, ['/opt/google/chrome', '--user-data-dir', '/different-profile'])
    assert.equal(clearStaleProfileLocks(item.profile, { host: 'old-container', procRoot: item.procRoot }).length, 3)
  } finally { item.close() }
})

test('a local Chrome without a matching lock hostname is still protected', () => {
  const item = fixture()
  try {
    processFixture(item, ['/opt/google/chrome', '--user-data-dir', realpathSync(item.profile)], '88')
    assert.throws(() => clearStaleProfileLocks(item.profile, { host: 'new-container', procRoot: item.procRoot }), /SRI_PROFILE_IN_USE/)
  } finally { item.close() }
})

test('unknown same-container locked process fails closed', () => {
  const item = fixture()
  try {
    processFixture(item, [])
    writeFileSync(join(item.procRoot, '331', 'cmdline'), '')
    assert.throws(() => clearStaleProfileLocks(item.profile, { host: 'old-container', procRoot: item.procRoot }), /SRI_PROFILE_PROCESS_UNVERIFIED/)
    assert.equal(lstatSync(join(item.profile, 'SingletonSocket')).isSymbolicLink(), true)
  } finally { item.close() }
})

test('non-link artifact and a symlinked profile directory are never removed', () => {
  const item = fixture()
  try {
    rmSync(join(item.profile, 'SingletonCookie'))
    mkdirSync(join(item.profile, 'SingletonCookie'))
    writeFileSync(join(item.profile, 'SingletonCookie', 'keep'), 'keep')
    assert.throws(() => clearStaleProfileLocks(item.profile, { procRoot: item.procRoot }), /ARTIFACT_UNSAFE/)
    assert.equal(readlinkSync(join(item.profile, 'SingletonSocket')), join(item.root, 'target'))
    symlinkSync(item.profile, join(item.root, 'linked-profile'))
    assert.throws(() => clearStaleProfileLocks(join(item.root, 'linked-profile'), { procRoot: item.procRoot }), /DIRECTORY_UNSAFE/)
  } finally { item.close() }
})
