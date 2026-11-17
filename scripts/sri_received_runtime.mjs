import { execFileSync } from 'node:child_process'
import { readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export function profileRoot(environment = process.env, platform = process.platform) {
  return environment.IAERP_SRI_PROFILE_ROOT ?? (platform === 'darwin'
    ? join(homedir(), 'Library', 'Application Support', 'IAERP')
    : join(homedir(), '.local', 'share', 'iaerp', 'sri-profiles'))
}

export function readServiceAccount(company) {
  const credentialsPath = process.env.IAERP_SRI_ACCOUNTS_FILE
  if (credentialsPath) {
    const info = statSync(credentialsPath)
    if (!info.isFile() || (info.mode & 0o077) !== 0) {
      throw new Error('IAERP_ACCOUNT_FILE_PERMISSIONS_INVALID')
    }
    const accounts = JSON.parse(readFileSync(credentialsPath, 'utf8'))
    const account = accounts[company.id]
    if (!account || typeof account.clientId !== 'string' || !account.clientId
      || typeof account.clientSecret !== 'string' || !account.clientSecret) { // pragma: allowlist secret -- type check
      throw new Error(`IAERP_ACCOUNT_CONFIGURATION_MISSING_${company.id}`)
    }
    return account
  }
  if (process.platform !== 'darwin') throw new Error('IAERP_ACCOUNT_FILE_REQUIRED')
  const read = (name) => {
    try {
      return execFileSync('/usr/bin/security', [
        'find-generic-password', '-s', company.iaerpKeychainService, '-a', name, '-w',
      ], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
    } catch {
      throw new Error(`KEYCHAIN_CONFIGURATION_MISSING_${company.id}`)
    }
  }
  return { clientId: read('client_id'), clientSecret: read('client_secret') }
}
