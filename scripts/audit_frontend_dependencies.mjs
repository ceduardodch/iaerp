import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const acceptedAdvisory = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf'
const frontendDirectory = fileURLToPath(new URL('../frontend/', import.meta.url))

export function blockingFindings(report, lock) {
  const findings = report.vulnerabilities
  const totals = report.metadata?.vulnerabilities
  if (report.error || !findings || typeof findings !== 'object' || Array.isArray(findings)
    || !totals) {
    throw new Error('La auditoría no devolvió un informe válido')
  }
  const severities = ['info', 'low', 'moderate', 'high', 'critical']
  if (Object.values(findings).some((finding) => !finding || !severities.includes(finding.severity))) {
    throw new Error('La auditoría devolvió una gravedad desconocida')
  }
  for (const severity of ['high', 'critical']) {
    const count = Object.values(findings).filter((finding) => finding.severity === severity).length
    if (!Number.isInteger(totals[severity]) || totals[severity] < 0 || totals[severity] !== count) {
      throw new Error('Los conteos de auditoría no coinciden con el informe')
    }
  }

  function coveredByException(name, visited = new Set()) {
    const finding = findings[name]
    if (!finding || finding.severity !== 'high' || visited.has(name)
      || !finding.via?.length || !finding.nodes?.length) {
      return false
    }
    if (!finding.nodes.every((node) => lock.packages?.[node]?.dev === true)) return false
    const nextVisited = new Set([...visited, name])
    return finding.via.every((cause) => {
      if (typeof cause === 'string') return coveredByException(cause, nextVisited)
      return name === 'picomatch'
        && cause.name === 'picomatch'
        && cause.url === acceptedAdvisory
        && cause.severity === 'high'
        && finding.nodes.every((node) => lock.packages[node].version === '4.0.7')
    })
  }

  return Object.keys(findings).filter((name) =>
    ['high', 'critical'].includes(findings[name].severity) && !coveredByException(name)
  )
}

function main() {
  const audit = spawnSync('npm', ['audit', '--json', '--audit-level=high'], {
    cwd: frontendDirectory,
    encoding: 'utf8',
    timeout: 120_000,
    maxBuffer: 10 * 1024 * 1024,
  })
  if (audit.error || ![0, 1].includes(audit.status)) {
    throw new Error('No se pudo completar npm audit')
  }
  const report = JSON.parse(audit.stdout)
  const lock = JSON.parse(readFileSync(resolve(frontendDirectory, 'package-lock.json'), 'utf8'))
  const blocked = blockingFindings(report, lock)
  if (blocked.length) {
    process.stderr.write(`Dependencias bloqueadas por auditoría: ${blocked.join(', ')}\n`)
    process.exitCode = 1
    return
  }
  const accepted = Object.values(report.vulnerabilities).filter((finding) =>
    ['high', 'critical'].includes(finding.severity)
  ).length
  process.stdout.write(accepted
    ? `Auditoría completa. Excepción autorizada GHSA-fc5q-39xc-vjpf en picomatch 4.0.7 de compilación (${accepted} dependencias afectadas).\n`
    : 'Auditoría completa sin hallazgos altos o críticos.\n')
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main()
  } catch (error) {
    process.stderr.write(`Auditoría fallida: ${error.message}\n`)
    process.exitCode = 1
  }
}
