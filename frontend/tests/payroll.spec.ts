import { expect, test, type Page } from '@playwright/test'

import { mockDashboardEndpoints } from './dashboard-mocks'
import { navigateToSection } from './navigation'

// Nómina: empleados y roles de pago mensuales. La API va mockeada con estado
// en memoria (como analytic-classifications.spec.ts) para poder encadenar
// alta → edición → baja y borrador → aprobación en el mismo test.

type Employee = {
  id: string
  fullName: string
  identificationNumber: string
  position: string | null
  sueldoMensual: string
  fechaIngreso: string
  fechaSalida: string | null
  active: boolean
  decimoTerceroMensualizado: boolean
  decimoCuartoMensualizado: boolean
  fondosReservaMensualizados: boolean
}

type Period = {
  id: string
  anio: number
  mes: number
  status: 'DRAFT' | 'APPROVED'
}

const EMPLOYEE_ID = '11111111-1111-4111-8111-111111111121'

function baseEmployee(overrides: Partial<Employee> = {}): Employee {
  return {
    id: EMPLOYEE_ID,
    fullName: 'María Torres',
    identificationNumber: '1712345678',
    position: 'Contadora',
    sueldoMensual: '900.00',
    fechaIngreso: '2025-01-15',
    fechaSalida: null,
    active: true,
    decimoTerceroMensualizado: true,
    decimoCuartoMensualizado: true,
    fondosReservaMensualizados: true,
    ...overrides,
  }
}

function entryFor(employeeId: string, periodId: string) {
  return {
    id: `${periodId}-${employeeId}`,
    periodId,
    employeeId,
    diasTrabajados: 30,
    imponible: '900.00',
    decimoTercero: '75.00',
    decimoCuarto: '40.17',
    fondosReserva: '0.00',
    totalIngresos: '1015.17',
    aporteIess: '85.05',
    totalDescuentos: '85.05',
    liquido: '930.12',
    sbuAplicado: '482.00',
    tasaIessAplicada: '0.0945',
    tasaFondosAplicada: '0.0833',
  }
}

/** Backend de nómina simulado en memoria; cada test arranca desde `employees`/`periods` propios. */
async function mockPayroll(page: Page, { employees = [] as Employee[], periods = [] as Period[] } = {}) {
  let nextEmployeeId = 900
  let nextPeriodId = 900
  const entriesByPeriod = new Map<string, ReturnType<typeof entryFor>[]>()
  for (const period of periods) {
    entriesByPeriod.set(period.id, employees.filter((employee) => employee.active).map((employee) => entryFor(employee.id, period.id)))
  }

  await page.route('**/api/v1/dev/token', (route) => route.fulfill({ json: { accessToken: 'test-token' } }))
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) => route.fulfill({
    json: {
      tenantId: '11111111-1111-4111-8111-111111111111',
      ruc: '1799999999001',
      name: 'IAERP Demo',
      roles: ['owner'],
      scopes: ['context:read', 'payroll:read', 'payroll:write'],
      automationWritesEnabled: false,
      defaultPaymentTermsDays: 0,
    },
  }))
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points', 'invoices', 'receivables']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }

  await page.route('**/api/v1/payroll/employees', async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as Omit<Employee, 'id' | 'active' | 'fechaSalida'>
      if (employees.some((employee) => employee.active && employee.identificationNumber === body.identificationNumber)) {
        await route.fulfill({ status: 409, json: { detail: 'Ya existe un empleado activo con esa identificación.' } })
        return
      }
      nextEmployeeId += 1
      const created: Employee = { ...body, id: `employee-${nextEmployeeId}`, active: true, fechaSalida: null }
      employees.push(created)
      await route.fulfill({ json: created })
      return
    }
    await route.fulfill({ json: employees.filter((employee) => employee.active) })
  })

  await page.route('**/api/v1/payroll/employees/*', async (route) => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').pop() as string
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON() as Omit<Employee, 'id' | 'active' | 'fechaSalida'>
      const employee = employees.find((candidate) => candidate.id === id)
      if (!employee) {
        await route.fulfill({ status: 404, json: { detail: 'No encontrado' } })
        return
      }
      Object.assign(employee, body)
      await route.fulfill({ json: employee })
      return
    }
    await route.fallback()
  })

  await page.route('**/api/v1/payroll/employees/*/terminate', async (route) => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').slice(-2)[0] as string
    const body = route.request().postDataJSON() as { fechaSalida: string }
    const employee = employees.find((candidate) => candidate.id === id)
    if (!employee) {
      await route.fulfill({ status: 404, json: { detail: 'No encontrado' } })
      return
    }
    employee.active = false
    employee.fechaSalida = body.fechaSalida
    await route.fulfill({ json: employee })
  })

  await page.route('**/api/v1/payroll/periods/draft', async (route) => {
    const body = route.request().postDataJSON() as { anio: number; mes: number }
    const existing = periods.find((period) => period.anio === body.anio && period.mes === body.mes)
    if (existing?.status === 'APPROVED') {
      await route.fulfill({ status: 409, json: { detail: 'El periodo ya fue aprobado y no se puede regenerar.' } })
      return
    }
    nextPeriodId += 1
    const period: Period = existing ?? { id: `period-${nextPeriodId}`, anio: body.anio, mes: body.mes, status: 'DRAFT' }
    if (!existing) periods.push(period)
    entriesByPeriod.set(period.id, employees.filter((employee) => employee.active).map((employee) => entryFor(employee.id, period.id)))
    await route.fulfill({ json: period })
  })

  await page.route('**/api/v1/payroll/periods', (route) => route.fulfill({ json: periods }))

  await page.route('**/api/v1/payroll/periods/*/approve', async (route) => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').slice(-2)[0] as string
    const period = periods.find((candidate) => candidate.id === id)
    if (!period) {
      await route.fulfill({ status: 404, json: { detail: 'No encontrado' } })
      return
    }
    period.status = 'APPROVED'
    await route.fulfill({ json: period })
  })

  await page.route('**/api/v1/payroll/periods/*/entries', async (route) => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').slice(-2)[0] as string
    await route.fulfill({ json: entriesByPeriod.get(id) ?? [] })
  })

  return { employees, periods }
}

async function openPayroll(page: Page) {
  await page.addInitScript(() => sessionStorage.clear())
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await navigateToSection(page, 'Nómina')
  await expect(page.getByRole('heading', { name: 'Nómina', exact: true })).toBeVisible()
}

test('muestra el estado vacío y da de alta un empleado nuevo', async ({ page }) => {
  await mockPayroll(page)
  await openPayroll(page)

  await expect(page.getByText('Sin empleados')).toBeVisible()
  await page.getByRole('button', { name: 'Nuevo empleado' }).first().click()

  await expect(page.getByRole('heading', { name: 'Nuevo empleado' })).toBeVisible()
  await page.getByLabel('Nombre completo').fill('Ana Salazar')
  await page.getByLabel('Identificación').fill('1723456789')
  await page.getByLabel('Cargo opcional').fill('Vendedora')
  await page.getByLabel('Sueldo mensual').fill('650')
  await page.getByLabel('Fecha de ingreso').fill('2026-02-01')
  await page.getByRole('button', { name: 'Guardar' }).click()

  const row = page.getByRole('row', { name: /Ana Salazar/ })
  await expect(row).toBeVisible()
  await expect(row).toContainText('1723456789')
  await expect(row).toContainText('Vendedora')
})

test('explica una identificación duplicada sin crear un segundo empleado', async ({ page }) => {
  await mockPayroll(page, { employees: [baseEmployee()] })
  await openPayroll(page)

  await page.getByRole('button', { name: 'Nuevo empleado' }).first().click()
  await page.getByLabel('Nombre completo').fill('Otra Persona')
  await page.getByLabel('Identificación').fill(baseEmployee().identificationNumber)
  await page.getByLabel('Sueldo mensual').fill('500')
  await page.getByLabel('Fecha de ingreso').fill('2026-02-01')
  await page.getByRole('button', { name: 'Guardar' }).click()

  await expect(page.getByRole('alert')).toContainText('Ya existe un empleado activo')
  await expect(page.getByRole('heading', { name: 'Nuevo empleado' })).toBeVisible()
})

test('edita el sueldo y el cargo de un empleado existente', async ({ page }) => {
  await mockPayroll(page, { employees: [baseEmployee()] })
  await openPayroll(page)

  await page.getByRole('row', { name: /María Torres/ }).getByRole('button', { name: 'Editar' }).click()
  await expect(page.getByRole('heading', { name: 'Editar a María Torres' })).toBeVisible()
  await page.getByLabel('Cargo opcional').fill('Gerente Financiera')
  await page.getByLabel('Sueldo mensual').fill('1200')
  await page.getByRole('button', { name: 'Guardar' }).click()

  const row = page.getByRole('row', { name: /María Torres/ })
  await expect(row).toContainText('Gerente Financiera')
})

test('da de baja a un empleado con fecha de salida y lo saca del listado', async ({ page }) => {
  await mockPayroll(page, { employees: [baseEmployee()] })
  await openPayroll(page)

  await page.getByRole('row', { name: /María Torres/ }).getByRole('button', { name: 'Dar de baja' }).click()
  const dialog = page.getByRole('dialog', { name: /Dar de baja a María Torres/ })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Fecha de salida').fill('2026-08-15')
  await dialog.getByRole('button', { name: 'Dar de baja' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('row', { name: /María Torres/ })).toHaveCount(0)
})

test('impide una fecha de salida anterior al ingreso', async ({ page }) => {
  await mockPayroll(page, { employees: [baseEmployee()] })
  await openPayroll(page)

  await page.getByRole('row', { name: /María Torres/ }).getByRole('button', { name: 'Dar de baja' }).click()
  const dialog = page.getByRole('dialog', { name: /Dar de baja a María Torres/ })
  const fechaSalida = dialog.getByLabel('Fecha de salida')
  await expect(fechaSalida).toHaveAttribute('min', baseEmployee().fechaIngreso)
})

test('genera el borrador de un periodo y muestra los roles calculados', async ({ page }) => {
  await mockPayroll(page, { employees: [baseEmployee()] })
  await openPayroll(page)

  await page.getByRole('tab', { name: 'Roles' }).click()
  await expect(page.getByText('Sin periodos')).toBeVisible()
  await page.getByLabel('Año').fill('2026')
  await page.getByLabel('Mes').fill('8')
  await page.getByRole('button', { name: 'Generar borrador' }).click()

  const periodRow = page.getByRole('row', { name: /Agosto de 2026/ })
  await expect(periodRow).toContainText('Borrador')
  await periodRow.getByRole('button', { name: 'Ver roles' }).click()

  const rolesPanel = page.getByRole('heading', { name: /Roles de Agosto de 2026/ }).locator('xpath=ancestor::section[1]')
  await expect(rolesPanel).toContainText('María Torres')
  await expect(rolesPanel).toContainText('SBU aplicado $482,00')
  await expect(rolesPanel).toContainText('aporte IESS 9,45%')
  await expect(rolesPanel).toContainText('$930,12')
})

test('aprueba un periodo y ya no ofrece regenerarlo', async ({ page }) => {
  await mockPayroll(page, { employees: [baseEmployee()] })
  await openPayroll(page)

  await page.getByRole('tab', { name: 'Roles' }).click()
  await page.getByLabel('Año').fill('2026')
  await page.getByLabel('Mes').fill('8')
  await page.getByRole('button', { name: 'Generar borrador' }).click()

  const periodRow = page.getByRole('row', { name: /Agosto de 2026/ })
  await periodRow.getByRole('button', { name: 'Aprobar' }).click()
  const dialog = page.getByRole('dialog', { name: /Aprobar Agosto de 2026/ })
  await dialog.getByRole('button', { name: 'Aprobar periodo' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(periodRow).toContainText('Aprobado')
  await expect(periodRow.getByRole('button', { name: 'Aprobar' })).toHaveCount(0)
})

test('bloquea con un mensaje claro regenerar un periodo ya aprobado', async ({ page }) => {
  await mockPayroll(page, { employees: [baseEmployee()], periods: [{ id: 'period-approved', anio: 2026, mes: 7, status: 'APPROVED' }] })
  await openPayroll(page)

  await page.getByRole('tab', { name: 'Roles' }).click()
  await expect(page.getByRole('row', { name: /Julio de 2026/ })).toContainText('Aprobado')
  await page.getByLabel('Año').fill('2026')
  await page.getByLabel('Mes').fill('7')
  await page.getByRole('button', { name: 'Generar borrador' }).click()

  await expect(page.getByRole('alert')).toContainText('ya fue aprobado')
})
