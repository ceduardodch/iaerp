export type TenantContext = {
  tenantId: string
  ruc: string
  name: string
  roles: string[]
  scopes: string[]
  automationWritesEnabled: boolean
}

export type Party = {
  id: string
  name: string
  identificationType: 'RUC' | 'CEDULA' | 'PASSPORT' | 'FINAL_CONSUMER'
  identificationNumber: string
  roles: Array<'CUSTOMER' | 'SUPPLIER'>
  email?: string
  phone?: string
  address?: string
}

export type Product = {
  id: string
  name: string
  code?: string
  unitPrice: string
  taxCategoryId: string
}

export type TaxCategory = {
  id: string
  sriCode: string
  name: string
  rate: string
  active: boolean
}

export type Establishment = {
  id: string
  code: string
  name: string
  address: string
  active: boolean
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const apiUrl = import.meta.env.VITE_API_URL ?? '/api/v1'

export async function apiRequest<T>(
  token: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { detail?: string; message?: string }
      | null
    throw new ApiError(
      body?.detail ?? body?.message ?? 'No se pudo completar la solicitud',
      response.status,
    )
  }
  return response.json() as Promise<T>
}

export function idempotencyKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`
}
