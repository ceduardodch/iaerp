import { linkSync, unlinkSync, writeFileSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { SRI_RECEIVED_COMPANIES } from '../../scripts/sri_received_companies.mjs'

const company = process.argv[2]
const mode = process.argv[3] ?? 'IMPORT'
const ids = company === 'all' ? SRI_RECEIVED_COMPANIES.map((item) => item.id) : [company]
if (!['IMPORT', 'DOWNLOAD', 'CHECK_ACCESS'].includes(mode)
  || ids.some((id) => !SRI_RECEIVED_COMPANIES.some((item) => item.id === id))) {
  throw new Error('Uso: node infra/sri-importer/request.mjs <empresa|all> [IMPORT|DOWNLOAD|CHECK_ACCESS]')
}
const temporary = '/data/request-' + randomUUID() + '.tmp'
try {
  writeFileSync(temporary, JSON.stringify({ companyIds: ids, mode }), {
    mode: 0o600, flag: 'wx',
  })
  linkSync(temporary, '/data/request.json')
} finally {
  unlinkSync(temporary)
}
process.stdout.write('Solicitud guardada para el importador del servidor.\n')
