import assert from 'node:assert/strict'
import test from 'node:test'

import { blockingFindings } from '../audit_frontend_dependencies.mjs'

function fixture() {
  return {
    report: {
      metadata: { vulnerabilities: { high: 2, critical: 0 } },
      vulnerabilities: {
        picomatch: {
          severity: 'high',
          nodes: ['node_modules/picomatch'],
          via: [{
            name: 'picomatch',
            severity: 'high',
            url: 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf',
          }],
        },
        vite: {
          severity: 'high',
          nodes: ['node_modules/vite'],
          via: ['picomatch'],
        },
      },
    },
    lock: {
      packages: {
        'node_modules/picomatch': { dev: true, version: '4.0.7' },
        'node_modules/vite': { dev: true, version: '8.3.5' },
      },
    },
  }
}

test('accepts only the authorized build advisory and its transitive findings', () => {
  const { report, lock } = fixture()
  assert.deepEqual(blockingFindings(report, lock), [])
})

test('blocks a second advisory even when the package also has the accepted advisory', () => {
  const { report, lock } = fixture()
  report.vulnerabilities.picomatch.via.push({
    name: 'picomatch', severity: 'high', url: 'https://github.com/advisories/another-advisory',
  })
  assert.deepEqual(blockingFindings(report, lock), ['picomatch', 'vite'])
})

test('blocks runtime packages, a changed version and critical findings', () => {
  for (const change of ['runtime', 'version', 'critical']) {
    const { report, lock } = fixture()
    if (change === 'runtime') lock.packages['node_modules/picomatch'].dev = false
    if (change === 'version') lock.packages['node_modules/picomatch'].version = '4.0.8'
    if (change === 'critical') report.vulnerabilities.picomatch.via[0].severity = 'critical'
    assert.deepEqual(blockingFindings(report, lock), ['picomatch', 'vite'])
  }
})

test('blocks unrecognized dependencies and cycles', () => {
  const { report, lock } = fixture()
  report.vulnerabilities.vite.via.push('missing-package')
  assert.deepEqual(blockingFindings(report, lock), ['vite'])
  report.vulnerabilities.picomatch.via = ['vite']
  assert.deepEqual(blockingFindings(report, lock), ['picomatch', 'vite'])
})

test('fails on incomplete audit reports and reports a critical package', () => {
  const { report, lock } = fixture()
  assert.throws(() => blockingFindings({}, lock), /informe válido/)
  assert.throws(() => blockingFindings({ error: {} }, lock), /informe válido/)
  report.vulnerabilities.picomatch.severity = 'critical'
  report.metadata.vulnerabilities = { high: 1, critical: 1 }
  assert.deepEqual(blockingFindings(report, lock), ['picomatch', 'vite'])
})

test('rejects incomplete or failed audit responses', () => {
  assert.throws(() => blockingFindings({}, {}), /informe válido/)
  const { report, lock } = fixture()
  report.error = { code: 'NETWORK_FAILURE' }
  assert.throws(() => blockingFindings(report, lock), /informe válido/)
})

test('rejects missing findings, an array and unknown severity', () => {
  const { report, lock } = fixture()
  assert.throws(() => blockingFindings({ ...report, vulnerabilities: {} }, lock), /conteos/)
  assert.throws(() => blockingFindings({ ...report, vulnerabilities: [] }, lock), /informe válido/)
  report.vulnerabilities.picomatch.severity = 'unknown'
  assert.throws(() => blockingFindings(report, lock), /gravedad desconocida/)
})
