import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Check, RefreshCw, X } from 'lucide-react'
import { api } from '../api'
import { useAutoRefresh, useConfigSlice } from '../hooks'
import type { Configuration, SettingsSection } from '../types'

export function SettingsPageShell({ kicker, title, description, notice, error, onDismiss, children }: {
  kicker: string; title: string; description: string; notice: string; error: string; onDismiss: () => void; children: ReactNode
}) {
  return (
    <div className="settings-page-single">
      <div className="page-heading"><div><div className="section-kicker">{kicker}</div><h1>{title}</h1><p>{description}</p></div></div>
      {(notice || error) && <div className={error ? 'workspace-alert' : 'workspace-notice'} role="status">{error || notice}<button type="button" onClick={onDismiss} aria-label="Dismiss"><X size={16} /></button></div>}
      {children}
    </div>
  )
}

function BillingSettingsPage() {
  const { value: billing, setValue: setBilling, error, setError, loading } = useConfigSlice((config) => config.billing)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!billing) return
    setSaving(true); setError(''); setNotice('')
    try {
      const updated = await api<Configuration>('/api/settings', { method: 'PATCH', body: JSON.stringify({ billing }) })
      setBilling(updated.billing); setNotice('Billing settings saved and audit-logged.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save billing settings.') }
    finally { setSaving(false) }
  }

  return (
    <SettingsPageShell kicker="SETTINGS / BILLING" title="Billing" description="What each SMS segment costs and when to alert on spend." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      {loading || !billing ? <div className="dashboard-loading">Loading billing settings…</div> : (
        <form className="settings-form-page" onSubmit={save}>
          <section className="md-card">
            <div className="settings-grid">
              <label>Cost per SMS segment<input type="number" min="0" step="0.01" value={billing.cost_per_segment_kes} onChange={(event) => setBilling({ ...billing, cost_per_segment_kes: event.target.value })} /></label>
              <label>Currency<input maxLength={3} value={billing.currency} onChange={(event) => setBilling({ ...billing, currency: event.target.value.toUpperCase() })} /></label>
              <label>Monthly budget<input type="number" min="0" step="0.01" value={billing.monthly_budget_kes} onChange={(event) => setBilling({ ...billing, monthly_budget_kes: event.target.value })} /></label>
              <label>Budget alert threshold (%)<input type="number" min="1" max="100" value={billing.alert_threshold_percent} onChange={(event) => setBilling({ ...billing, alert_threshold_percent: Number(event.target.value) })} /></label>
            </div>
          </section>
          <div className="settings-save-row"><span>Changes are recorded in the audit log.</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save billing'} <Check size={15} /></button></div>
        </form>
      )}
    </SettingsPageShell>
  )
}

function GatewaySettingsPage() {
  const { value: gateway, setValue: setGateway, error, setError, loading } = useConfigSlice((config) => config.gateway)
  const [allowedSenders, setAllowedSenders] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [clientId, setClientId] = useState('')
  const [accessKey, setAccessKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')

  useEffect(() => { if (gateway) setAllowedSenders(gateway.allowed_sender_ids.join(', ')) }, [gateway])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!gateway) return
    setSaving(true); setError(''); setNotice('')
    const senders = allowedSenders.split(',').map((value) => value.trim().toUpperCase()).filter(Boolean)
    const payload = {
      base_url: gateway.base_url || null, default_sender_id: gateway.default_sender_id, allowed_sender_ids: senders,
      ...(apiKey ? { api_key: apiKey } : {}), ...(clientId ? { client_id: clientId } : {}), ...(accessKey ? { access_key: accessKey } : {}),
    }
    try {
      const updated = await api<Configuration>('/api/settings', { method: 'PATCH', body: JSON.stringify({ gateway: payload }) })
      setGateway(updated.gateway); setApiKey(''); setClientId(''); setAccessKey(''); setNotice('Gateway settings saved and audit-logged.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save gateway settings.') }
    finally { setSaving(false) }
  }

  return (
    <SettingsPageShell kicker="SETTINGS / GATEWAY" title="Gateway connection" description="Onfon Media (Service B) base URL, credentials, and registered Sender IDs." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      {loading || !gateway ? <div className="dashboard-loading">Loading gateway settings…</div> : (
        <form className="settings-form-page" onSubmit={save}>
          <section className="md-card">
            <div className="settings-grid">
              <label className="wide-setting">Base URL<input type="url" value={gateway.base_url ?? ''} onChange={(event) => setGateway({ ...gateway, base_url: event.target.value })} placeholder="https://api.onfonmedia.co.ke/v1/sms/SendBulkSMS" /></label>
              <label>Default Sender ID<input value={gateway.default_sender_id} onChange={(event) => setGateway({ ...gateway, default_sender_id: event.target.value.toUpperCase() })} maxLength={11} /></label>
              <label>Allowed Sender IDs<input value={allowedSenders} onChange={(event) => setAllowedSenders(event.target.value)} placeholder="UPENFLOW, UPENFLOW2" /><small>Separate registered IDs with commas.</small></label>
              <label className="secret-field">Client ID <span>{gateway.has_client_id ? 'Saved value is masked' : 'Not configured'}</span><input type="password" autoComplete="new-password" value={clientId} onChange={(event) => setClientId(event.target.value)} placeholder={gateway.has_client_id ? 'Enter a new value to rotate' : 'Onfon ClientId'} /></label>
              <label className="secret-field">API key <span>{gateway.has_api_key ? 'Saved key is masked' : 'Not configured'}</span><input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={gateway.has_api_key ? 'Enter a new key to rotate' : 'Onfon ApiKey'} /></label>
              <label className="secret-field">Access key <span>{gateway.has_access_key ? 'Saved value is masked' : 'Not configured'}</span><input type="password" autoComplete="new-password" value={accessKey} onChange={(event) => setAccessKey(event.target.value)} placeholder={gateway.has_access_key ? 'Enter a new value to rotate' : 'Sent as the AccessKey header'} /></label>
            </div>
            <p className="inline-instruction">All three credentials are required before sends will go out — the worker skips sending (messages stay Queued) until Client ID, API key, and Access key are all configured.</p>
          </section>
          <div className="settings-save-row"><span>Changes are recorded in the audit log.</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save gateway'} <Check size={15} /></button></div>
        </form>
      )}
    </SettingsPageShell>
  )
}

function LimitsSettingsPage() {
  const { value: limits, setValue: setLimits, error, setError, loading } = useConfigSlice((config) => config.limits)
  const [timezone, setTimezone] = useState('')
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [configLoaded, setConfigLoaded] = useState(false)

  useEffect(() => {
    api<Configuration>('/api/settings').then((config) => setTimezone(config.timezone)).catch(() => undefined).finally(() => setConfigLoaded(true))
  }, [])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!limits) return
    setSaving(true); setError(''); setNotice('')
    try {
      const updated = await api<Configuration>('/api/settings', { method: 'PATCH', body: JSON.stringify({ limits, timezone }) })
      setLimits(updated.limits); setTimezone(updated.timezone); setNotice('Delivery limits saved and audit-logged.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save delivery limits.') }
    finally { setSaving(false) }
  }

  return (
    <SettingsPageShell kicker="SETTINGS / LIMITS" title="Delivery limits" description="Send rate, segment cap, retries, and the workspace timezone." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      {loading || !limits || !configLoaded ? <div className="dashboard-loading">Loading delivery limits…</div> : (
        <form className="settings-form-page" onSubmit={save}>
          <section className="md-card">
            <div className="settings-grid">
              <label>Send rate (SMS/second)<input type="number" min="1" value={limits.send_rate_per_second} onChange={(event) => setLimits({ ...limits, send_rate_per_second: Number(event.target.value) })} /></label>
              <label>Maximum segments<input type="number" min="1" max="3" value={limits.max_segments} onChange={(event) => setLimits({ ...limits, max_segments: Number(event.target.value) })} /></label>
              <label>Stale queue cutoff (minutes)<input type="number" min="1" value={limits.stale_queue_minutes} onChange={(event) => setLimits({ ...limits, stale_queue_minutes: Number(event.target.value) })} /></label>
              <label>Retry attempts<input type="number" min="1" max="10" value={limits.retry_attempts} onChange={(event) => setLimits({ ...limits, retry_attempts: Number(event.target.value) })} /></label>
              <label>Timezone<input value={timezone} onChange={(event) => setTimezone(event.target.value)} /></label>
            </div>
          </section>
          <div className="settings-save-row"><span>Changes are recorded in the audit log.</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save limits'} <Check size={15} /></button></div>
        </form>
      )}
    </SettingsPageShell>
  )
}

function SafeguardsSettingsPage() {
  const { value: safety, setValue: setSafety, error, setError, loading } = useConfigSlice((config) => config.safety)
  const [testAllowlist, setTestAllowlist] = useState('')
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')

  useEffect(() => { if (safety) setTestAllowlist(safety.test_allowlist.join(', ')) }, [safety])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!safety) return
    setSaving(true); setError(''); setNotice('')
    const payload = { ...safety, test_allowlist: testAllowlist.split(',').map((number) => number.trim()).filter(Boolean) }
    try {
      const updated = await api<Configuration>('/api/settings', { method: 'PATCH', body: JSON.stringify({ safety: payload }) })
      setSafety(updated.safety); setNotice('Customer safeguards saved and audit-logged.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save customer safeguards.') }
    finally { setSaving(false) }
  }

  return (
    <SettingsPageShell kicker="SETTINGS / SAFEGUARDS" title="Customer safeguards" description="Throttling, duplicate protection, and test mode." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      {loading || !safety ? <div className="dashboard-loading">Loading safeguards…</div> : (
        <form className="settings-form-page" onSubmit={save}>
          <section className="md-card">
            <div className="settings-grid">
              <label>Maximum SMS per recipient / hour<input type="number" min="1" value={safety.max_per_recipient_hour} onChange={(event) => setSafety({ ...safety, max_per_recipient_hour: Number(event.target.value) })} /></label>
              <label>Duplicate content window (minutes)<input type="number" min="1" value={safety.duplicate_window_minutes} onChange={(event) => setSafety({ ...safety, duplicate_window_minutes: Number(event.target.value) })} /></label>
              <label className="config-toggle"><span><strong>Test mode</strong><small>Only send to allowlisted numbers.</small></span><input type="checkbox" checked={safety.test_mode} onChange={(event) => setSafety({ ...safety, test_mode: event.target.checked })} /></label>
              <label className="config-toggle"><span><strong>Fake gateway</strong><small>Record test sends without delivery.</small></span><input type="checkbox" checked={safety.fake_gateway} onChange={(event) => setSafety({ ...safety, fake_gateway: event.target.checked })} /></label>
              <label className="wide-setting">Test number allowlist<input value={testAllowlist} onChange={(event) => setTestAllowlist(event.target.value)} placeholder="0712345678, 254110123456" /><small>Only Kenyan mobile numbers are accepted.</small></label>
            </div>
          </section>
          <div className="settings-save-row"><span>Changes are recorded in the audit log.</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save safeguards'} <Check size={15} /></button></div>
        </form>
      )}
    </SettingsPageShell>
  )
}

function QuietHoursSettingsPage() {
  const { value: quietHours, setValue: setQuietHours, error, setError, loading } = useConfigSlice((config) => config.quiet_hours)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!quietHours) return
    setSaving(true); setError(''); setNotice('')
    try {
      const updated = await api<Configuration>('/api/settings', { method: 'PATCH', body: JSON.stringify({ quiet_hours: quietHours }) })
      setQuietHours(updated.quiet_hours); setNotice('Quiet hours saved and audit-logged.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save quiet hours.') }
    finally { setSaving(false) }
  }

  return (
    <SettingsPageShell kicker="SETTINGS / QUIET HOURS" title="Quiet hours" description="Hold outbound sends overnight, resuming automatically once the window ends." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      {loading || !quietHours ? <div className="dashboard-loading">Loading quiet hours…</div> : (
        <form className="settings-form-page" onSubmit={save}>
          <section className="md-card">
            <div className="settings-grid">
              <label className="config-toggle wide-setting"><span><strong>Enable quiet hours</strong><small>Queue messages during the window below.</small></span><input type="checkbox" checked={quietHours.enabled} onChange={(event) => setQuietHours({ ...quietHours, enabled: event.target.checked })} /></label>
              <label>Start (HH:MM, local time)<input value={quietHours.start} onChange={(event) => setQuietHours({ ...quietHours, start: event.target.value })} placeholder="21:00" /></label>
              <label>End (HH:MM, local time)<input value={quietHours.end} onChange={(event) => setQuietHours({ ...quietHours, end: event.target.value })} placeholder="07:00" /></label>
            </div>
          </section>
          <div className="settings-save-row"><span>Changes are recorded in the audit log.</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save quiet hours'} <Check size={15} /></button></div>
        </form>
      )}
    </SettingsPageShell>
  )
}

function RetentionSettingsPage() {
  const { value: retention, setValue: setRetention, error, setError, loading } = useConfigSlice((config) => config.retention)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!retention) return
    setSaving(true); setError(''); setNotice('')
    try {
      const updated = await api<Configuration>('/api/settings', { method: 'PATCH', body: JSON.stringify({ retention }) })
      setRetention(updated.retention); setNotice('Data retention saved and audit-logged.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save data retention.') }
    finally { setSaving(false) }
  }

  return (
    <SettingsPageShell kicker="SETTINGS / RETENTION" title="Data retention" description="How long messages and audit history are kept before automatic cleanup." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      {loading || !retention ? <div className="dashboard-loading">Loading retention settings…</div> : (
        <form className="settings-form-page" onSubmit={save}>
          <section className="md-card">
            <div className="settings-grid">
              <label>Message retention (days)<input type="number" min="1" value={retention.message_retention_days} onChange={(event) => setRetention({ ...retention, message_retention_days: Number(event.target.value) })} /></label>
              <label>Audit log retention (days)<input type="number" min="1" value={retention.audit_log_retention_days} onChange={(event) => setRetention({ ...retention, audit_log_retention_days: Number(event.target.value) })} /></label>
            </div>
          </section>
          <div className="settings-save-row"><span>Changes are recorded in the audit log.</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save retention'} <Check size={15} /></button></div>
        </form>
      )}
    </SettingsPageShell>
  )
}

function MonitoringSettingsPage() {
  const { value: monitoring, setValue: setMonitoring, error, setError, loading } = useConfigSlice((config) => config.monitoring)
  const [alertEmails, setAlertEmails] = useState('')
  const [slackWebhook, setSlackWebhook] = useState('')
  const [telegramToken, setTelegramToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [balance, setBalance] = useState<{ balance_kes: string | null; checked_at: string | null } | null>(null)
  const [checkingBalance, setCheckingBalance] = useState(false)

  useEffect(() => {
    api<Configuration>('/api/settings').then((config) => setAlertEmails(config.alert_emails.join(', '))).catch(() => undefined)
  }, [])

  async function loadBalance(silent = false) {
    try { setBalance(await api('/api/settings/balance')) }
    catch (reason) { if (!silent) setError(reason instanceof Error ? reason.message : 'Unable to load balance.') }
  }
  useEffect(() => { void loadBalance() }, [])
  useAutoRefresh(() => { void loadBalance(true) }, 60000)

  async function checkBalanceNow() {
    setCheckingBalance(true); setError(''); setNotice('')
    try {
      setBalance(await api('/api/settings/balance/check', { method: 'POST' }))
      setNotice('Balance refreshed.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to check the balance right now.') }
    finally { setCheckingBalance(false) }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!monitoring) return
    setSaving(true); setError(''); setNotice('')
    const payload = {
      ...monitoring,
      ...(slackWebhook ? { slack_webhook_url: slackWebhook } : {}),
      ...(telegramToken ? { telegram_bot_token: telegramToken } : {}),
    }
    try {
      const updated = await api<Configuration>('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({ monitoring: payload, alert_emails: alertEmails.split(',').map((email) => email.trim()).filter(Boolean) }),
      })
      setMonitoring(updated.monitoring); setAlertEmails(updated.alert_emails.join(', ')); setSlackWebhook(''); setTelegramToken(''); setNotice('Monitoring & alerts saved and audit-logged.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save monitoring settings.') }
    finally { setSaving(false) }
  }

  return (
    <SettingsPageShell kicker="SETTINGS / MONITORING" title="Monitoring & alerts" description="Who gets paged, and over which channels, when something needs attention." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      {loading || !monitoring ? <div className="dashboard-loading">Loading monitoring settings…</div> : (
        <form className="settings-form-page" onSubmit={save}>
          <section className="md-card balance-card">
            <div className="section-heading"><div><span className="section-kicker">GATEWAY CREDIT</span><h2>SMS balance</h2></div></div>
            {balance?.balance_kes ? (
              <>
                <strong className="balance-amount">KES {Number(balance.balance_kes).toLocaleString(undefined, { maximumFractionDigits: 2 })}</strong>
                <small>Last checked {balance.checked_at ? new Date(balance.checked_at).toLocaleString() : 'never'}</small>
              </>
            ) : <p className="inline-instruction">No balance recorded yet — configure the gateway credentials above and check now, or wait for the next periodic check.</p>}
            <button className="secondary-button compact-button" type="button" disabled={checkingBalance} onClick={() => void checkBalanceNow()}><RefreshCw size={13} /> {checkingBalance ? 'Checking…' : 'Check now'}</button>
          </section>
          <section className="md-card">
            <div className="settings-grid">
              <label className="wide-setting">Alert emails<input value={alertEmails} onChange={(event) => setAlertEmails(event.target.value)} placeholder="ops@upenflow.co.ke, oncall@upenflow.co.ke" /></label>
              <label>Service A silence alert (minutes)<input type="number" min="1" value={monitoring.service_a_silence_minutes} onChange={(event) => setMonitoring({ ...monitoring, service_a_silence_minutes: Number(event.target.value) })} /></label>
              <label>Service B error-rate threshold (%)<input type="number" min="1" max="100" value={monitoring.error_rate_threshold_percent} onChange={(event) => setMonitoring({ ...monitoring, error_rate_threshold_percent: Number(event.target.value) })} /></label>
              <label>Low credit threshold (KES)<input type="number" min="0" value={monitoring.low_credit_kes} onChange={(event) => setMonitoring({ ...monitoring, low_credit_kes: event.target.value })} /></label>
              <label className="config-toggle"><span><strong>Check balance periodically</strong><small>Runs in the background and alerts below the threshold above.</small></span><input type="checkbox" checked={monitoring.balance_check_enabled} onChange={(event) => setMonitoring({ ...monitoring, balance_check_enabled: event.target.checked })} /></label>
              <label>Balance check interval (minutes)<input type="number" min="5" max="1440" value={monitoring.balance_check_interval_minutes} onChange={(event) => setMonitoring({ ...monitoring, balance_check_interval_minutes: Number(event.target.value) })} disabled={!monitoring.balance_check_enabled} /></label>
              <label>On-call SMS number<input value={monitoring.oncall_phone ?? ''} onChange={(event) => setMonitoring({ ...monitoring, oncall_phone: event.target.value })} placeholder="0712345678" /></label>
              <label className="secret-field">Slack webhook <span>{monitoring.has_slack_webhook ? 'Saved webhook is masked' : 'Not configured'}</span><input type="password" autoComplete="new-password" value={slackWebhook} onChange={(event) => setSlackWebhook(event.target.value)} placeholder={monitoring.has_slack_webhook ? 'Enter a new URL to rotate' : 'https://hooks.slack.com/...'} /></label>
              <label className="secret-field">Telegram bot token <span>{monitoring.has_telegram_bot_token ? 'Saved token is masked' : 'Not configured'}</span><input type="password" autoComplete="new-password" value={telegramToken} onChange={(event) => setTelegramToken(event.target.value)} placeholder={monitoring.has_telegram_bot_token ? 'Enter a new token to rotate' : 'Bot token'} /></label>
              <label>Telegram chat ID<input value={monitoring.telegram_chat_id ?? ''} onChange={(event) => setMonitoring({ ...monitoring, telegram_chat_id: event.target.value })} /></label>
            </div>
          </section>
          <div className="settings-save-row"><span>Changes are recorded in the audit log.</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save monitoring'} <Check size={15} /></button></div>
        </form>
      )}
    </SettingsPageShell>
  )
}

function NetworkPrefixesSettingsPage() {
  const { value: networkPrefixes, setValue: setNetworkPrefixes, error, setError, loading } = useConfigSlice(
    (config) => Object.fromEntries(Object.entries(config.network_prefixes).map(([network, prefixes]) => [network, prefixes.join(', ')]))
  )
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!networkPrefixes) return
    setSaving(true); setError(''); setNotice('')
    const payload = Object.fromEntries(
      Object.entries(networkPrefixes).map(([network, value]) => [network, value.split(',').map((prefix) => prefix.trim()).filter(Boolean)])
    )
    try {
      const updated = await api<Configuration>('/api/settings', { method: 'PATCH', body: JSON.stringify({ network_prefixes: payload }) })
      setNetworkPrefixes(Object.fromEntries(Object.entries(updated.network_prefixes).map(([network, prefixes]) => [network, prefixes.join(', ')])))
      setNotice('Network prefixes saved and audit-logged.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save network prefixes.') }
    finally { setSaving(false) }
  }

  return (
    <SettingsPageShell kicker="SETTINGS / NETWORK" title="Network prefixes" description="The carrier-detection table used to tag messages Safaricom, Airtel, or Telkom." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      {loading || !networkPrefixes ? <div className="dashboard-loading">Loading network prefixes…</div> : (
        <form className="settings-form-page" onSubmit={save}>
          <section className="md-card">
            <div className="settings-grid">
              {Object.entries(networkPrefixes).map(([network, value]) => <label className="wide-setting" key={network}>{network} prefixes<input value={value} onChange={(event) => setNetworkPrefixes({ ...networkPrefixes, [network]: event.target.value })} /></label>)}
            </div>
          </section>
          <div className="settings-save-row"><span>Changes are recorded in the audit log.</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save network prefixes'} <Check size={15} /></button></div>
        </form>
      )}
    </SettingsPageShell>
  )
}

export function SettingsRouter({ section }: { section: SettingsSection }) {
  switch (section) {
    case 'billing': return <BillingSettingsPage />
    case 'gateway': return <GatewaySettingsPage />
    case 'limits': return <LimitsSettingsPage />
    case 'safety': return <SafeguardsSettingsPage />
    case 'quiet-hours': return <QuietHoursSettingsPage />
    case 'retention': return <RetentionSettingsPage />
    case 'monitoring': return <MonitoringSettingsPage />
    case 'network': return <NetworkPrefixesSettingsPage />
  }
}
