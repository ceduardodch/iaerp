import { existsSync, fstatSync, lstatSync, readFileSync, readlinkSync, readdirSync, realpathSync, unlinkSync } from 'node:fs'
import { hostname } from 'node:os'
import { basename, dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { SRI_RECEIVED_COMPANIES } from '../../scripts/sri_received_companies.mjs'
import { profileRoot } from '../../scripts/sri_received_runtime.mjs'

const ARTIFACTS = ['SingletonSocket', 'SingletonCookie', 'SingletonLock']

function profileArgument(argv) {
  const equals = argv.find((arg) => arg.startsWith('--user-data-dir='))
  if (equals) return equals.slice('--user-data-dir='.length)
  const index = argv.indexOf('--user-data-dir')
  return index >= 0 ? argv[index + 1] : undefined
}

// Call only while entrypoint holds /data/importer.lock. A foreign container's
// hostname/PID cannot be checked in this namespace; flock excludes its runner.
// First rollout from a legacy runner without flock requires stopping it first.
export function clearStaleProfileLocks(profile, { host = hostname(), procRoot = '/proc' } = {}) {
  let directory
  try { directory = lstatSync(profile) } catch (error) {
    if (error.code === 'ENOENT') return []
    throw error
  }
  if (!directory.isDirectory() || directory.isSymbolicLink()) throw new Error('SRI_PROFILE_DIRECTORY_UNSAFE')
  const parent = lstatSync(dirname(profile))
  if (!parent.isDirectory() || parent.isSymbolicLink()) throw new Error('SRI_PROFILE_PARENT_UNSAFE')
  const canonical = realpathSync(profile)
  const artifacts = ARTIFACTS.flatMap((name) => {
    const path = join(canonical, name)
    let stat
    try { stat = lstatSync(path) } catch (error) {
      if (error.code === 'ENOENT') return []
      throw error
    }
    // Never follow links or remove directories/files that could contain data.
    if (!stat.isSymbolicLink()) throw new Error('SRI_PROFILE_LOCK_ARTIFACT_UNSAFE')
    return [{ name, path, target: readlinkSync(path) }]
  })
  const lock = artifacts.find((artifact) => artifact.name === 'SingletonLock')
  const match = lock ? /^(.*)-([1-9]\d*)$/.exec(lock.target) : null
  if (lock && !match) throw new Error('SRI_PROFILE_LOCK_TARGET_INVALID')
  const localLockPid = match?.[1] === host ? match[2] : null
  // Also detect a local browser if its lock link was removed independently.
  for (const pid of readdirSync(procRoot).filter((name) => /^\d+$/.test(name))) {
    const pidPath = join(procRoot, pid)
    let argv
    try {
      argv = readFileSync(join(pidPath, 'cmdline'), 'utf8').split('\0').filter(Boolean)
    } catch (error) {
      if (pid === localLockPid && error.code !== 'ENOENT') throw new Error('SRI_PROFILE_PROCESS_UNVERIFIED')
      continue // Processes can disappear while /proc is being inspected.
    }
    if (pid === localLockPid && argv.length === 0) throw new Error('SRI_PROFILE_PROCESS_UNVERIFIED')
    const argument = profileArgument(argv)
    const executable = basename(argv[0] ?? '')
    if (!/^(chrome|chromium|chromium-browser)$/.test(executable) || !argument) continue
    let requested
    try {
      const absolute = isAbsolute(argument) ? argument : resolve(readlinkSync(join(pidPath, 'cwd')), argument)
      requested = existsSync(absolute) ? realpathSync(absolute) : resolve(absolute)
    } catch {
      throw new Error('SRI_PROFILE_PROCESS_UNVERIFIED')
    }
    if (requested === canonical) throw new Error('SRI_PROFILE_IN_USE')
  }
  for (const artifact of artifacts) unlinkSync(artifact.path)
  return artifacts.map((artifact) => artifact.name)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.env.IAERP_SRI_IMPORTER_LOCK_FD !== '9' || !fstatSync(9).isFile()) {
    throw new Error('SRI_IMPORTER_KERNEL_LOCK_REQUIRED')
  }
  for (const company of SRI_RECEIVED_COMPANIES) {
    clearStaleProfileLocks(join(profileRoot(), company.browserProfile))
  }
}
