import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdirSync, readFileSync, renameSync, writeFileSync, existsSync } from 'node:fs'
import { createServer } from 'node:http'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

import { chromium } from '../../frontend/node_modules/playwright/index.mjs'
import { SRI_RECEIVED_COMPANIES } from '../../scripts/sri_received_companies.mjs'
import { fiscalPeriodForYesterday, runCompany } from '../../scripts/sri_received_reports_to_iaerp.mjs'
import { profileRoot } from '../../scripts/sri_received_runtime.mjs'
import { fiscalDay, importIsDue, interruptRun, recoverRunState } from './schedule.mjs'

const statePath = '/data/status.json'
const controlPath = '/data/request.json'
const children = []
const contexts = new Map()
let stopping = false
let running = false
const status = recoverRunState(existsSync(statePath) ? JSON.parse(readFileSync(statePath, 'utf8')) : {})
status.results ??= {}

function saveStatus() {
  status.updatedAt = new Date().toISOString()
  writeFileSync(statePath + '.tmp', JSON.stringify(status), { mode: 0o600 })
  renameSync(statePath + '.tmp', statePath)
}

async function stop() {
  if (stopping) return
  stopping = true
  interruptRun(status)
  saveStatus()
  await Promise.all([...contexts.values()].map((context) => context.close().catch(() => {})))
  for (const child of children) child.kill('SIGTERM')
  process.exit(0)
}

function start(command, args) {
  const child = spawn(command, args, { stdio: ['ignore', 'ignore', 'ignore'] })
  children.push(child)
  child.on('error', () => { process.stderr.write('SRI_DISPLAY_PROCESS_FAILED\n'); void stop() })
  child.on('exit', () => {
    if (!stopping) { process.stderr.write('SRI_DISPLAY_PROCESS_STOPPED\n'); void stop() }
  })
}

async function runImports(companyIds, mode = 'IMPORT') {
  if (running) return
  running = true
  status.running = true
  saveStatus()
  try {
    for (const company of SRI_RECEIVED_COMPANIES.filter((item) => companyIds.includes(item.id))) {
      try {
        const result = await runCompany(company, fiscalPeriodForYesterday(), {
          mode: { IMPORT: null, DOWNLOAD: '--download-only', CHECK_ACCESS: '--check-access' }[mode],
          manualCaptcha: false,
          existingSession: mode !== 'CHECK_ACCESS',
          browserContext: contexts.get(company.id),
          captchaHandler: async (page, reportType) => {
            status.results[company.id] = {
              status: 'CAPTCHA_REQUIRED', at: new Date().toISOString(), reportType,
            }
            saveStatus()
            await page.bringToFront()
            try {
              await page.waitForFunction(() => {
                const text = document.body.innerText
                const rejected = /captcha/i.test(text) && /error|incorrect|inválid|invalido/i.test(text)
                return !rejected && (
                  /No existen datos para los parámetros ingresados/i.test(text)
                  || Array.from(document.querySelectorAll('a')).some((link) =>
                    link.textContent.trim() === 'Descargar reporte' && link.getClientRects().length > 0)
                )
              }, null, { timeout: 10 * 60_000 })
            } catch {
              throw new Error('SRI_CAPTCHA_REQUIRED')
            }
          },
        })
        status.results[company.id] = { status: 'COMPLETED', at: new Date().toISOString(), ...result }
        process.stdout.write(JSON.stringify(status.results[company.id]) + '\n')
      } catch (error) {
        // runCompany only returns sanitized stage/error codes.
        status.results[company.id] = {
          status: 'ATTENTION', at: new Date().toISOString(), error: error.message,
        }
        process.stderr.write(JSON.stringify({ company: company.id, ...status.results[company.id] }) + '\n')
      }
      saveStatus()
    }
  } finally {
    running = false
    status.running = false
    saveStatus()
  }
}

process.on('SIGTERM', () => { void stop() })
process.on('SIGINT', () => { void stop() })
mkdirSync(profileRoot(), { recursive: true, mode: 0o700 })
// Coolify may attach a shared internal network; require VNC authentication too.
const vncPasswordPath = '/data/vnc-password'
if (!existsSync(vncPasswordPath)) {
  writeFileSync(vncPasswordPath, randomBytes(6).toString('base64'), { mode: 0o600, flag: 'wx' })
}
start('Xvfb', [':99', '-screen', '0', '1440x1000x24', '-nolisten', 'tcp', '-ac'])
await delay(1000)
start('openbox', [])
start('x11vnc', ['-display', ':99', '-localhost', '-forever', '-shared', '-passwdfile', vncPasswordPath, '-rfbport', '5900'])
start('websockify', ['--web=/usr/share/novnc', '0.0.0.0:6080', '127.0.0.1:5900'])

for (const company of SRI_RECEIVED_COMPANIES) {
  const context = await chromium.launchPersistentContext(join(profileRoot(), company.browserProfile), {
    headless: false,
    locale: 'es-EC',
    timezoneId: 'America/Guayaquil',
    viewport: { width: 1366, height: 900 },
    acceptDownloads: true,
    chromiumSandbox: true,
    args: ['--restore-last-session'],
  })
  context.on('close', () => { if (!stopping) void stop() })
  contexts.set(company.id, context)
  const page = context.pages()[0] ?? await context.newPage()
  if (page.url() === 'about:blank' && process.env.IAERP_SRI_BROWSER_SMOKE !== '1') {
    await page.goto('https://srienlinea.sri.gob.ec/tuportal-internet/', {
      waitUntil: 'domcontentloaded', timeout: 30_000,
    }).catch(() => {})
  }
}

// Health endpoint is private to the container network and returns no fiscal data.
createServer((_request, response) => {
  response.writeHead(contexts.size === SRI_RECEIVED_COMPANIES.length ? 200 : 503)
  response.end('ok')
}).listen(6081, '127.0.0.1')
saveStatus()

while (!stopping) {
  if (existsSync(controlPath)) {
    renameSync(controlPath, controlPath + '.handled')
    try {
      const request = JSON.parse(readFileSync(controlPath + '.handled', 'utf8'))
      const ids = request.companyIds ?? []
      const mode = request.mode ?? 'IMPORT'
      if (Array.isArray(ids) && ids.length
        && ['IMPORT', 'DOWNLOAD', 'CHECK_ACCESS'].includes(mode)
        && ids.every((id) => SRI_RECEIVED_COMPANIES.some((item) => item.id === id))) {
        await runImports(ids, mode)
      } else {
        process.stderr.write('SRI_CONTROL_REQUEST_INVALID\n')
      }
    } catch {
      process.stderr.write('SRI_CONTROL_REQUEST_INVALID\n')
    }
  }
  if (!stopping && process.env.IAERP_SRI_SCHEDULE_ENABLED === 'true' && importIsDue(status.lastAttemptDay)) {
    status.lastAttemptDay = fiscalDay()
    saveStatus()
    await runImports(SRI_RECEIVED_COMPANIES.map((company) => company.id))
  }
  saveStatus()
  await delay(30_000)
}
