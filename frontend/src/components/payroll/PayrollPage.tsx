import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  apiRequest,
  idempotencyKey,
  type PayrollEmployee,
  type PayrollEmployeeInput,
  type PayrollEntry,
  type PayrollPeriod,
  type PayrollPeriodDraftInput,
} from '../../api'
import {
  ErpActionCell,
  ErpButton,
  ErpDataTable,
  ErpEmptyState,
  ErpFormPanel,
  ErpPageHeader,
  ErpPanel,
  ErpStatusBadge,
  ErpTabs,
  ErpToolbar,
} from '../erp'
import { ErpConfirmDialog } from '../erp/ErpConfirmDialog'
import './PayrollPage.css'

const amountFormatter = new Intl.NumberFormat('es-EC', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatAmount(value: string | number): string {
  const amount = Number(value)
  return Number.isFinite(amount) ? amountFormatter.format(amount) : '0,00'
}

function formatPercent(value: string): string {
  return `${formatAmount(Number(value) * 100)}%`
}

function today(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Guayaquil' })
}

function periodLabel(period: Pick<PayrollPeriod, 'anio' | 'mes'>): string {
  const fecha = new Date(`${period.anio}-${String(period.mes).padStart(2, '0')}-01T12:00:00`)
  const etiqueta = fecha.toLocaleDateString('es-EC', { month: 'long', year: 'numeric' })
  return etiqueta.charAt(0).toUpperCase() + etiqueta.slice(1)
}

interface EmployeeFormProps {
  token: string
  employee?: PayrollEmployee
  onSaved: () => void
  onCancel: () => void
}

function EmployeeForm({ token, employee, onSaved, onCancel }: EmployeeFormProps) {
  const [decimoTercero, setDecimoTercero] = useState(employee?.decimoTerceroMensualizado ?? true)
  const [decimoCuarto, setDecimoCuarto] = useState(employee?.decimoCuartoMensualizado ?? true)
  const [fondosReserva, setFondosReserva] = useState(employee?.fondosReservaMensualizados ?? true)
  const save = useMutation({
    mutationFn: (payload: PayrollEmployeeInput) => employee
      ? apiRequest<PayrollEmployee>(token, `/payroll/employees/${employee.id}`, {
        method: 'PUT',
        headers: { 'Idempotency-Key': idempotencyKey('web-payroll-employee-update') },
        body: JSON.stringify(payload),
      })
      : apiRequest<PayrollEmployee>(token, '/payroll/employees', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-payroll-employee-create') },
        body: JSON.stringify(payload),
      }),
    onSuccess: onSaved,
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    save.mutate({
      fullName: String(form.get('fullName')),
      identificationNumber: String(form.get('identificationNumber')),
      position: String(form.get('position') || '') || null,
      sueldoMensual: String(form.get('sueldoMensual')),
      fechaIngreso: String(form.get('fechaIngreso')),
      decimoTerceroMensualizado: decimoTercero,
      decimoCuartoMensualizado: decimoCuarto,
      fondosReservaMensualizados: fondosReserva,
    })
  }

  return (
    <ErpFormPanel
      eyebrow="Nómina"
      title={employee ? `Editar a ${employee.fullName}` : 'Nuevo empleado'}
      pending={save.isPending}
      error={save.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <div className="payroll-form-grid">
        <label>Nombre completo<input name="fullName" required minLength={1} maxLength={200} defaultValue={employee?.fullName ?? ''} /></label>
        <label>Identificación<input name="identificationNumber" required minLength={1} maxLength={20} defaultValue={employee?.identificationNumber ?? ''} /></label>
        <label>Cargo opcional<input name="position" maxLength={120} defaultValue={employee?.position ?? ''} /></label>
        <label>Sueldo mensual<input name="sueldoMensual" type="number" min="0" step="0.01" required defaultValue={employee?.sueldoMensual ?? ''} /></label>
        <label>Fecha de ingreso<input name="fechaIngreso" type="date" required defaultValue={employee?.fechaIngreso ?? today()} /></label>
      </div>
      <fieldset className="payroll-form-checks">
        <legend>Mensualización</legend>
        <label><input type="checkbox" checked={decimoTercero} onChange={(event) => setDecimoTercero(event.target.checked)} /> Décimo tercero mensualizado</label>
        <label><input type="checkbox" checked={decimoCuarto} onChange={(event) => setDecimoCuarto(event.target.checked)} /> Décimo cuarto mensualizado</label>
        <label><input type="checkbox" checked={fondosReserva} onChange={(event) => setFondosReserva(event.target.checked)} /> Fondos de reserva mensualizados</label>
      </fieldset>
    </ErpFormPanel>
  )
}

function TerminateEmployeeDialog({ token, employee, onCancel, onSaved }: {
  token: string
  employee: PayrollEmployee
  onCancel: () => void
  onSaved: () => void
}) {
  const [fechaSalida, setFechaSalida] = useState(today())
  const terminate = useMutation({
    mutationFn: () => apiRequest<PayrollEmployee>(token, `/payroll/employees/${employee.id}/terminate`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-payroll-employee-terminate') },
      body: JSON.stringify({ fechaSalida }),
    }),
    onSuccess: onSaved,
  })

  return (
    <ErpConfirmDialog
      title={`Dar de baja a ${employee.fullName}`}
      danger
      confirmLabel="Dar de baja"
      pending={terminate.isPending}
      onCancel={onCancel}
      onConfirm={() => terminate.mutate()}
      description={<>
        <p>Deja de generar rol de pagos a partir del mes siguiente a la fecha de salida. El mes en que sale se prorratea por días trabajados.</p>
        <label>Fecha de salida<input type="date" required value={fechaSalida} min={employee.fechaIngreso} onChange={(event) => setFechaSalida(event.target.value)} /></label>
        {terminate.error ? <p className="form-error" role="alert">{terminate.error.message}</p> : null}
      </>}
    />
  )
}

function EmployeesTab({ token, employees, isPending, error, onCreate }: {
  token: string
  employees: PayrollEmployee[]
  isPending: boolean
  error?: string
  onCreate: () => void
}) {
  const queryClient = useQueryClient()
  const [editingEmployee, setEditingEmployee] = useState<PayrollEmployee | null>(null)
  const [terminatingEmployee, setTerminatingEmployee] = useState<PayrollEmployee | null>(null)

  if (editingEmployee) {
    return (
      <EmployeeForm
        token={token}
        employee={editingEmployee}
        onCancel={() => setEditingEmployee(null)}
        onSaved={() => { setEditingEmployee(null); void queryClient.invalidateQueries({ queryKey: ['payroll-employees'] }) }}
      />
    )
  }

  return (
    <>
      <ErpPanel title="Empleados" count={employees.length}>
        {isPending ? <p aria-busy="true">Cargando empleados…</p> : null}
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <ErpDataTable
          ariaLabel="Empleados de nómina"
          rows={employees}
          rowKey={(employee) => employee.id}
          emptyState={<ErpEmptyState title="Sin empleados" description="Da de alta al primer empleado para poder generar roles de pago." action={<ErpButton variant="primary" onClick={onCreate}>Nuevo empleado</ErpButton>} />}
          columns={[
            { header: 'Nombre', cell: (employee) => employee.fullName },
            { header: 'Identificación', cell: (employee) => employee.identificationNumber },
            { header: 'Cargo', cell: (employee) => employee.position ?? '—' },
            { header: 'Sueldo mensual', cell: (employee) => `$${formatAmount(employee.sueldoMensual)}` },
            { header: 'Ingreso', cell: (employee) => employee.fechaIngreso },
            {
              header: 'Acciones',
              cell: (employee) => (
                <ErpActionCell>
                  <ErpButton variant="ghost" onClick={() => setEditingEmployee(employee)}>Editar</ErpButton>
                  <ErpButton variant="ghost" onClick={() => setTerminatingEmployee(employee)}>Dar de baja</ErpButton>
                </ErpActionCell>
              ),
            },
          ]}
        />
      </ErpPanel>
      {terminatingEmployee ? (
        <TerminateEmployeeDialog
          token={token}
          employee={terminatingEmployee}
          onCancel={() => setTerminatingEmployee(null)}
          onSaved={() => { setTerminatingEmployee(null); void queryClient.invalidateQueries({ queryKey: ['payroll-employees'] }) }}
        />
      ) : null}
    </>
  )
}

function PeriodEntries({ token, period, employees, onClose }: {
  token: string
  period: PayrollPeriod
  employees: PayrollEmployee[]
  onClose: () => void
}) {
  const entriesQuery = useQuery({
    queryKey: ['payroll-periods', period.id, 'entries'],
    queryFn: () => apiRequest<PayrollEntry[]>(token, `/payroll/periods/${period.id}/entries`),
  })
  const entries = entriesQuery.data ?? []
  const firstEntry = entries[0]

  function employeeName(employeeId: string): string {
    return employees.find((employee) => employee.id === employeeId)?.fullName ?? 'Empleado dado de baja'
  }

  return (
    <ErpPanel title={`Roles de ${periodLabel(period)}`} count={entries.length} actions={<ErpButton variant="ghost" onClick={onClose}>Cerrar</ErpButton>}>
      {entriesQuery.isPending ? <p aria-busy="true">Cargando roles…</p> : null}
      {entriesQuery.error ? <p className="form-error" role="alert">{entriesQuery.error.message}</p> : null}
      {firstEntry ? (
        <p className="fine-print">
          SBU aplicado ${formatAmount(firstEntry.sbuAplicado)} · aporte IESS {formatPercent(firstEntry.tasaIessAplicada)} · fondos de reserva {formatPercent(firstEntry.tasaFondosAplicada)}
        </p>
      ) : null}
      <ErpDataTable
        ariaLabel={`Roles calculados de ${periodLabel(period)}`}
        rows={entries}
        rowKey={(entry) => entry.id}
        emptyState={<ErpEmptyState title="Sin roles" description="Este periodo no tiene empleados vigentes en esas fechas." />}
        columns={[
          { header: 'Empleado', cell: (entry) => employeeName(entry.employeeId) },
          { header: 'Días trabajados', cell: (entry) => entry.diasTrabajados },
          { header: 'Imponible', cell: (entry) => `$${formatAmount(entry.imponible)}` },
          { header: 'Décimo tercero', cell: (entry) => `$${formatAmount(entry.decimoTercero)}` },
          { header: 'Décimo cuarto', cell: (entry) => `$${formatAmount(entry.decimoCuarto)}` },
          { header: 'Fondos de reserva', cell: (entry) => `$${formatAmount(entry.fondosReserva)}` },
          { header: 'Total ingresos', cell: (entry) => `$${formatAmount(entry.totalIngresos)}` },
          { header: 'Aporte IESS', cell: (entry) => `$${formatAmount(entry.aporteIess)}` },
          { header: 'Líquido a recibir', cell: (entry) => `$${formatAmount(entry.liquido)}` },
        ]}
      />
    </ErpPanel>
  )
}

function PeriodsTab({ token, employees }: { token: string; employees: PayrollEmployee[] }) {
  const queryClient = useQueryClient()
  const [selectedPeriodId, setSelectedPeriodId] = useState<string | null>(null)
  const [approvingPeriod, setApprovingPeriod] = useState<PayrollPeriod | null>(null)
  const periodsQuery = useQuery({
    queryKey: ['payroll-periods'],
    queryFn: () => apiRequest<PayrollPeriod[]>(token, '/payroll/periods'),
  })
  const periods = [...(periodsQuery.data ?? [])].sort((izquierda, derecha) => (
    derecha.anio - izquierda.anio || derecha.mes - izquierda.mes
  ))
  const selectedPeriod = periods.find((period) => period.id === selectedPeriodId) ?? null
  const generateDraft = useMutation({
    mutationFn: (payload: PayrollPeriodDraftInput) => apiRequest<PayrollPeriod>(token, '/payroll/periods/draft', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-payroll-period-draft') },
      body: JSON.stringify(payload),
    }),
    onSuccess: (period) => {
      void queryClient.invalidateQueries({ queryKey: ['payroll-periods'] })
      setSelectedPeriodId(period.id)
    },
  })
  const approvePeriod = useMutation({
    mutationFn: (periodId: string) => apiRequest<PayrollPeriod>(token, `/payroll/periods/${periodId}/approve`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-payroll-period-approve') },
    }),
    onSuccess: () => {
      setApprovingPeriod(null)
      void queryClient.invalidateQueries({ queryKey: ['payroll-periods'] })
    },
  })

  function submitDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    generateDraft.mutate({ anio: Number(form.get('anio')), mes: Number(form.get('mes')) })
  }

  const now = new Date()
  return (
    <>
      <ErpPanel title="Generar borrador del mes">
        <p className="fine-print">Genera (o regenera) el rol de todos los empleados vigentes en ese mes. Un periodo ya aprobado no se puede regenerar.</p>
        <form className="payroll-form-grid" onSubmit={submitDraft}>
          <label>Año<input name="anio" type="number" min={2000} max={2100} required defaultValue={now.getFullYear()} /></label>
          <label>Mes<input name="mes" type="number" min={1} max={12} required defaultValue={now.getMonth() + 1} /></label>
          {generateDraft.error ? <p className="form-error" role="alert">{generateDraft.error.message}</p> : null}
          <ErpButton variant="primary" type="submit" disabled={generateDraft.isPending}>{generateDraft.isPending ? 'Generando…' : 'Generar borrador'}</ErpButton>
        </form>
      </ErpPanel>
      <ErpPanel title="Periodos" count={periods.length}>
        {periodsQuery.isPending ? <p aria-busy="true">Cargando periodos…</p> : null}
        {periodsQuery.error ? <p className="form-error" role="alert">{periodsQuery.error.message}</p> : null}
        <ErpDataTable
          ariaLabel="Periodos de nómina"
          rows={periods}
          rowKey={(period) => period.id}
          emptyState={<ErpEmptyState title="Sin periodos" description="Genera el borrador de un mes para empezar." />}
          columns={[
            { header: 'Periodo', cell: (period) => periodLabel(period) },
            { header: 'Estado', cell: (period) => <ErpStatusBadge tone={period.status === 'APPROVED' ? 'success' : 'warning'}>{period.status === 'APPROVED' ? 'Aprobado' : 'Borrador'}</ErpStatusBadge> },
            {
              header: 'Acciones',
              cell: (period) => (
                <ErpActionCell>
                  <ErpButton variant="ghost" onClick={() => setSelectedPeriodId(period.id)}>Ver roles</ErpButton>
                  {period.status === 'DRAFT' ? <ErpButton variant="ghost" onClick={() => setApprovingPeriod(period)}>Aprobar</ErpButton> : null}
                </ErpActionCell>
              ),
            },
          ]}
        />
      </ErpPanel>
      {selectedPeriod ? (
        <PeriodEntries token={token} period={selectedPeriod} employees={employees} onClose={() => setSelectedPeriodId(null)} />
      ) : null}
      {approvingPeriod ? (
        <ErpConfirmDialog
          title={`Aprobar ${periodLabel(approvingPeriod)}`}
          description={<>
            <p>Una vez aprobado, este periodo ya no se puede regenerar. Revisa los roles antes de confirmar.</p>
            {approvePeriod.error ? <p className="form-error" role="alert">{approvePeriod.error.message}</p> : null}
          </>}
          confirmLabel="Aprobar periodo"
          pending={approvePeriod.isPending}
          onCancel={() => setApprovingPeriod(null)}
          onConfirm={() => approvePeriod.mutate(approvingPeriod.id)}
        />
      ) : null}
    </>
  )
}

export function PayrollPage({ token }: { token: string }) {
  const [view, setView] = useState<'EMPLOYEES' | 'PERIODS'>('EMPLOYEES')
  const [isCreatingEmployee, setIsCreatingEmployee] = useState(false)
  const queryClient = useQueryClient()
  const employeesQuery = useQuery({
    queryKey: ['payroll-employees'],
    queryFn: () => apiRequest<PayrollEmployee[]>(token, '/payroll/employees'),
  })
  const employees = employeesQuery.data ?? []

  if (isCreatingEmployee) {
    return (
      <EmployeeForm
        token={token}
        onCancel={() => setIsCreatingEmployee(false)}
        onSaved={() => { setIsCreatingEmployee(false); void queryClient.invalidateQueries({ queryKey: ['payroll-employees'] }) }}
      />
    )
  }

  return (
    <>
      <ErpPageHeader
        eyebrow="Nómina"
        title="Nómina"
        subtitle="Empleados y roles de pago mensuales, calculados con las reglas del IESS vigentes."
        actions={view === 'EMPLOYEES' ? <ErpButton variant="secondary" onClick={() => setIsCreatingEmployee(true)}>Nuevo empleado</ErpButton> : undefined}
      />
      <ErpToolbar ariaLabel="Secciones de nómina">
        <ErpTabs
          ariaLabel="Secciones de nómina"
          value={view}
          onChange={setView}
          tabs={[
            { value: 'EMPLOYEES', label: 'Empleados' },
            { value: 'PERIODS', label: 'Roles' },
          ]}
        />
      </ErpToolbar>
      {view === 'EMPLOYEES' ? (
        <EmployeesTab
          token={token}
          employees={employees}
          isPending={employeesQuery.isPending}
          error={employeesQuery.error?.message}
          onCreate={() => setIsCreatingEmployee(true)}
        />
      ) : (
        <PeriodsTab token={token} employees={employees} />
      )}
    </>
  )
}
