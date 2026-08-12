import type { Lead } from '../../api'
import { ErpEmptyState, ErpPanel, ErpStatusBadge } from '../erp'

type CampaignSummary = {
  key: string
  name: string
  source: string
  total: number
  qualified: number
  won: number
}

function campaignSummaries(leads: Lead[]): CampaignSummary[] {
  const summaries = new Map<string, CampaignSummary>()
  for (const lead of leads) {
    if (!lead.campaignId && !lead.campaignName && !lead.utmCampaign) continue
    const key = lead.campaignId ?? lead.utmCampaign ?? lead.campaignName ?? lead.id
    const current = summaries.get(key) ?? {
      key,
      name: lead.campaignName ?? lead.utmCampaign ?? 'Campaña sin nombre',
      source: lead.source ?? 'Sin origen',
      total: 0,
      qualified: 0,
      won: 0,
    }
    current.total += 1
    if (lead.qualificationStatus === 'QUALIFIED') current.qualified += 1
    if (lead.status === 'WON') current.won += 1
    summaries.set(key, current)
  }
  return [...summaries.values()].sort((left, right) => right.total - left.total || left.name.localeCompare(right.name, 'es'))
}

export function CampaignLeadSummary({ leads }: { leads: Lead[] }) {
  const campaigns = campaignSummaries(leads)
  return (
    <ErpPanel title="Campañas y captación" count={campaigns.length} className="campaign-summary-panel">
      {campaigns.length === 0 ? (
        <ErpEmptyState title="Sin leads atribuidos" description="Los leads que lleguen desde redes mostrarán aquí su campaña y conversión comercial." />
      ) : (
        <details className="campaign-summary-details">
          <summary>Ver rendimiento de campañas</summary>
          <div className="erp-table-wrap">
          <table className="campaign-summary-table">
            <thead><tr><th>Campaña</th><th>Origen</th><th>Captados</th><th>Calificados</th><th>Ganados</th></tr></thead>
            <tbody>{campaigns.map((campaign) => <tr key={campaign.key}><td><strong>{campaign.name}</strong></td><td><ErpStatusBadge tone="neutral">{campaign.source}</ErpStatusBadge></td><td>{campaign.total}</td><td><span aria-label={`Calificados: ${campaign.qualified}`}>{campaign.qualified}</span></td><td><span aria-label={`Ganados: ${campaign.won}`}>{campaign.won}</span></td></tr>)}</tbody>
          </table>
          </div>
        </details>
      )}
    </ErpPanel>
  )
}
