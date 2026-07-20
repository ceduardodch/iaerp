import type { LeadStatus } from '../api'

/**
 * Convención de pipeline del CRM (solo cliente).
 *
 * El backend NO restringe transiciones (contrato fijado por sus tests:
 * NEW→WON directo es válido vía API). Estas reglas existen para que la UI
 * guíe un flujo comercial coherente en drag & drop, quick-add y bulk-move:
 * - Las etapas avanzan de una en una hacia adelante.
 * - LOST es alcanzable desde cualquier etapa activa (descartar).
 * - WON solo desde NEGOTIATION.
 * - WON y LOST son terminales: de ahí no se mueve nada.
 */
const VALID_TRANSITIONS: Record<LeadStatus, readonly LeadStatus[]> = {
  NEW: ['CONTACTED', 'LOST'],
  CONTACTED: ['QUALIFIED', 'LOST'],
  QUALIFIED: ['PROPOSAL', 'LOST'],
  PROPOSAL: ['NEGOTIATION', 'LOST'],
  NEGOTIATION: ['WON', 'LOST'],
  WON: [],
  LOST: [],
}

/** ¿Es válido mover un lead de `from` a `to` según la convención del pipeline? */
export function isValidLeadTransition(from: LeadStatus, to: LeadStatus): boolean {
  return VALID_TRANSITIONS[from].includes(to)
}

/**
 * Quick-add crea siempre en NEW (backend); solo se encadena un salto si la
 * columna destino es alcanzable en UNA transición válida desde NEW.
 */
export function isQuickAddSingleHop(target: LeadStatus): boolean {
  return VALID_TRANSITIONS.NEW.includes(target) && target !== 'LOST'
}
