import { useEffect, useState } from 'react'
import { ChevronDown, Download } from 'lucide-react'
import { api } from '../api'
import { useAutoRefresh } from '../hooks'
import type { Dashboard, Rule } from '../types'

function changeTone(change: number): string {
  if (change > 0) return 'tone-green'
  if (change < 0) return 'tone-red'
  return 'tone-neutral'
}

export function DashboardPage() {
  const [period, setPeriod] = useState<'daily' | 'weekly' | 'monthly' | 'custom'>('weekly')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [ruleFilter, setRuleFilter] = useState('')
  const [networkFilter, setNetworkFilter] = useState('')
  const [rules, setRules] = useState<Rule[]>([])
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')

  useEffect(() => { api<Rule[]>('/api/rules').then(setRules).catch(() => undefined) }, [])

  function params() {
    const query = new URLSearchParams({ period })
    if (period === 'custom' && customFrom && customTo) { query.set('start', customFrom); query.set('end', customTo) }
    if (ruleFilter) query.set('rule_id', ruleFilter)
    if (networkFilter) query.set('network', networkFilter)
    return query
  }

  async function load(silent = false) {
    if (period === 'custom' && (!customFrom || !customTo)) return
    try { setData(await api<Dashboard>(`/api/dashboard?${params()}`)); setError('') }
    catch (reason) { if (!silent) setError(reason instanceof Error ? reason.message : 'Unable to load dashboard.') }
  }
  useEffect(() => { void load() }, [period, customFrom, customTo, ruleFilter, networkFilter])
  useAutoRefresh(() => { void load(true) }, 30000)

  if (error) return <div className="dashboard-page"><div className="workspace-alert" role="alert">{error}</div></div>
  if (!data) return <div className="dashboard-page"><div className="dashboard-loading">Loading dashboard…</div></div>

  const cards = [
    { label: 'Received', key: 'received' as const, note: 'all inbound messages' },
    { label: 'Sent', key: 'sent' as const, note: 'handed to the gateway' },
    { label: 'Delivered', key: 'delivered' as const, note: `${data.kpis.delivered.rate ?? 0}% delivery rate` },
    { label: 'Failed', key: 'failed' as const, note: `${data.kpis.failed.rate ?? 0}% failure rate` },
    { label: 'Unmapped', key: 'unmapped' as const, note: 'no rule matched' },
    { label: 'Total cost', key: 'total_cost_kes' as const, note: 'KES this period', money: true },
    { label: 'Avg cost / SMS', key: 'avg_cost_per_sms_kes' as const, note: 'KES per message', money: true },
  ]
  const maxRuleCount = Math.max(1, ...data.charts.by_rule.map((item) => item.count))
  const maxNetworkCount = Math.max(1, ...data.charts.by_network.map((item) => item.count))
  const maxTimeseries = Math.max(1, ...data.charts.timeseries.map((item) => item.sent + item.failed))
  const maxHour = Math.max(1, ...data.charts.hour_heatmap.map((item) => item.count))

  return <div className="dashboard-page">
    <div className="page-heading"><div><div className="section-kicker">OPERATIONS / 06</div><h1>Dashboard</h1><p>Current message flow, delivery, and cost.</p></div><span className={`dashboard-switch state-${data.sending_state}`}>SENDING {data.sending_state.toUpperCase()}</span></div>
    <div className="dashboard-toolbar">
      <div className="period-toggle">{(['daily', 'weekly', 'monthly', 'custom'] as const).map((value) => <button key={value} type="button" className={period === value ? 'selected' : ''} onClick={() => setPeriod(value)}>{value}</button>)}</div>
      {period === 'custom' && <><input type="date" value={customFrom} onChange={(event) => setCustomFrom(event.target.value)} /><input type="date" value={customTo} onChange={(event) => setCustomTo(event.target.value)} /></>}
      <label className="filter-select"><span>Rule</span><select value={ruleFilter} onChange={(event) => setRuleFilter(event.target.value)}><option value="">All rules</option>{rules.map((rule) => <option key={rule.id} value={rule.id}>{rule.name}</option>)}</select><ChevronDown size={14} /></label>
      <label className="filter-select"><span>Network</span><select value={networkFilter} onChange={(event) => setNetworkFilter(event.target.value)}><option value="">All networks</option>{['Safaricom', 'Airtel', 'Telkom'].map((value) => <option key={value}>{value}</option>)}</select><ChevronDown size={14} /></label>
      <a className="secondary-button export-button" href={`/api/dashboard/export.csv?${params()}`}><Download size={14} /> CSV</a>
      <a className="secondary-button export-button" href={`/api/dashboard/export.pdf?${params()}`}><Download size={14} /> PDF</a>
    </div>
    <div className="dashboard-kpis">
      {cards.map((card) => { const kpi = data.kpis[card.key]; return (
        <section className={`kpi-card ${changeTone(kpi.change_percent)}`} key={card.label}>
          <span>{card.label}</span>
          <strong>{card.money ? `KES ${kpi.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : kpi.value.toLocaleString()}</strong>
          <small>{card.note}</small>
          <em className="kpi-change">{kpi.change_percent >= 0 ? '+' : ''}{kpi.change_percent}% vs previous</em>
          <i />
        </section>
      ) })}
      <section className="kpi-card tone-neutral">
        <span>Budget used</span>
        <strong>{data.budget_used_percent}%</strong>
        <small>of KES {data.budget_kes.toLocaleString()} monthly budget</small>
        <i />
      </section>
    </div>
    <div className="dashboard-lower">
      <section className="dashboard-panel">
        <div className="section-heading"><div><span className="section-kicker">VOLUME OVER TIME</span><h2>Sent / delivered / failed</h2></div><span className="section-meta">{data.charts.granularity === 'hour' ? 'BY HOUR' : 'BY DAY'}</span></div>
        {data.charts.timeseries.length ? <div className="timeseries-chart">{data.charts.timeseries.map((point) => <div className="timeseries-bar" key={point.period} title={`${point.period}: ${point.sent} sent, ${point.failed} failed`}><div className="timeseries-stack"><i className="bar-delivered" style={{ height: `${Math.max(2, point.delivered / maxTimeseries * 100)}%` }} /><i className="bar-sent" style={{ height: `${Math.max(0, (point.sent - point.delivered) / maxTimeseries * 100)}%` }} /><i className="bar-failed" style={{ height: `${Math.max(0, point.failed / maxTimeseries * 100)}%` }} /></div><small>{point.period.slice(5)}</small></div>)}</div> : <div className="dashboard-empty">No messages in this period yet.</div>}
      </section>
      <section className="dashboard-panel status-panel">
        <div className="section-heading"><div><span className="section-kicker">BY HOUR OF DAY</span><h2>Traffic heatmap</h2></div></div>
        <div className="hour-heatmap">{data.charts.hour_heatmap.map((item) => <span key={item.hour} title={`${item.hour}:00 — ${item.count}`} style={{ opacity: 0.15 + (item.count / maxHour) * 0.85 }} />)}</div>
      </section>
    </div>
    <div className="dashboard-lower">
      <section className="dashboard-panel">
        <div className="section-heading"><div><span className="section-kicker">ROUTING PERFORMANCE</span><h2>Volume &amp; cost by rule</h2></div><span className="section-meta">TOP 10</span></div>
        {data.charts.by_rule.length ? <div className="rule-bars">{data.charts.by_rule.map((item) => <div className="rule-bar-row" key={item.rule}><span>{item.rule}</span><div><i style={{ width: `${Math.max(4, item.count / maxRuleCount * 100)}%` }} /></div><strong>{item.count} · KES {item.cost_kes.toFixed(0)}</strong></div>)}</div> : <div className="dashboard-empty">Matched messages will appear here.</div>}
      </section>
      <section className="dashboard-panel status-panel">
        <div className="section-heading"><div><span className="section-kicker">NETWORK SPLIT</span><h2>Volume by network</h2></div></div>
        {data.charts.by_network.length ? <div className="rule-bars">{data.charts.by_network.map((item) => <div className="rule-bar-row" key={item.network}><span>{item.network}</span><div><i style={{ width: `${Math.max(4, item.count / maxNetworkCount * 100)}%` }} /></div><strong>{item.count}</strong></div>)}</div> : <div className="dashboard-empty">Network data will appear here.</div>}
        <div className="status-total"><span>Queue depth</span><strong>{data.queued}</strong></div>
      </section>
    </div>
  </div>
}
