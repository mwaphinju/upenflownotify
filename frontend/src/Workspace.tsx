import { useEffect, useState, type FormEvent } from 'react'
import { ArrowDown, ArrowUp, ArrowUpRight, Ban, Check, ChevronDown, ChevronLeft, ChevronRight, CirclePlus, Clock, Download, FlaskConical, History, KeyRound, LogOut, Pause, Pencil, Play, RefreshCw, Search, Square, Trash2, UserRound, X } from 'lucide-react'

type User = { name: string; email: string; role: string }
type Rule = {
  id: number
  name: string
  priority: number
  match_type: 'contains' | 'starts_with' | 'exact' | 'regex'
  match_value: string
  case_sensitive: boolean
  sender_id: string
  outbound_template: string
  is_enabled: boolean
  version: number
}
type RuleDraft = Omit<Rule, 'id' | 'version'>
type RuleVersion = { version: number; snapshot: Record<string, unknown>; created_by: number | null; created_at: string }
type TestResult = {
  rule: Rule | null
  status: string
  rendered_text: string | null
  character_count?: number
  encoding?: string
  segments: number
  warnings: string[]
}
type ManagedUser = { id: number; name: string; email: string; role: string; is_active: boolean; password_set: boolean }
type ActiveSession = { id: number; device: string; ip_address: string | null; last_seen_at: string; current: boolean }
type SendingState = { state: 'on' | 'paused' | 'stopped'; queued_count: number; test_mode: boolean }
type Message = {
  id: number; message_id: string; received_at: string; recipient: string; order_ref: string | null
  sender_id: string | null; network: string | null; segments: number | null; cost_kes: number | null
  inbound_preview: string; sms_preview: string | null; status: string; status_reason: string | null
}
type TimelineEvent = { status: string; at: string | null }
type MessageDetail = Message & {
  inbound_text: string; rendered_text: string | null; rule: string | null; rule_version: number | null
  raw_payload: Record<string, unknown>; rate_per_segment_kes: number | null; attempts: number; error: string | null
  provider_message_id: string | null; timeline: TimelineEvent[]; can_resend: boolean
}
type KpiValue = { value: number; change_percent: number; rate?: number }
type Dashboard = {
  period: { label: string; start: string; end: string }
  kpis: Record<'received' | 'sent' | 'delivered' | 'failed' | 'unmapped' | 'total_cost_kes' | 'avg_cost_per_sms_kes', KpiValue>
  budget_kes: number
  budget_used_percent: number
  charts: {
    granularity: string
    timeseries: { period: string; sent: number; delivered: number; failed: number; cost_kes: number }[]
    by_rule: { rule: string; count: number; cost_kes: number }[]
    by_network: { network: string; count: number }[]
    hour_heatmap: { hour: number; count: number }[]
  }
  sending_state: string
  queued: number
  test_mode: boolean
}
type Configuration = {
  billing: { cost_per_segment_kes: string; currency: string; monthly_budget_kes: string; alert_threshold_percent: number; network_rates: Record<string, string> }
  gateway: { base_url: string | null; username: string | null; api_key: string | null; has_api_key: boolean; default_sender_id: string; allowed_sender_ids: string[] }
  limits: { send_rate_per_second: number; max_segments: number; stale_queue_minutes: number; retry_attempts: number }
  safety: { max_per_recipient_hour: number; duplicate_window_minutes: number; test_mode: boolean; fake_gateway: boolean; test_allowlist: string[] }
  quiet_hours: { enabled: boolean; start: string; end: string }
  retention: { message_retention_days: number; audit_log_retention_days: number }
  monitoring: {
    service_a_silence_minutes: number; error_rate_threshold_percent: number; low_credit_kes: string
    slack_webhook_url: string | null; has_slack_webhook: boolean; telegram_bot_token: string | null; has_telegram_bot_token: boolean
    telegram_chat_id: string | null; oncall_phone: string | null
  }
  network_prefixes: Record<string, string[]>
  timezone: string
  alert_emails: string[]
}

const emptyDraft: RuleDraft = {
  name: '', priority: 10, match_type: 'contains', match_value: '', case_sensitive: false,
  sender_id: 'UPENFLOW', outbound_template: '', is_enabled: true,
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? 'The request could not be completed.')
  }
  return response.status === 204 ? undefined as T : response.json()
}

function RuleEditor({
  initial,
  onClose,
  onSave,
}: {
  initial: RuleDraft
  onClose: () => void
  onSave: (draft: RuleDraft) => Promise<void>
}) {
  const [draft, setDraft] = useState(initial)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const change = <K extends keyof RuleDraft>(key: K, value: RuleDraft[K]) => setDraft((current) => ({ ...current, [key]: value }))

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      await onSave(draft)
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to save this rule.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="rule-dialog" role="dialog" aria-modal="true" aria-labelledby="rule-dialog-title">
        <div className="dialog-heading"><div><span className="section-kicker">MAPPING RULE</span><h2 id="rule-dialog-title">{initial.name ? 'Edit rule' : 'New rule'}</h2></div><button className="quiet-icon" type="button" onClick={onClose} aria-label="Close"><X size={18} /></button></div>
        <form className="rule-form" onSubmit={submit}>
          <label>Rule name<input value={draft.name} onChange={(event) => change('name', event.target.value)} required maxLength={120} placeholder="e.g. Order dispatched" /></label>
          <div className="form-grid-two">
            <label>Match type<span className="select-wrap"><select value={draft.match_type} onChange={(event) => change('match_type', event.target.value as RuleDraft['match_type'])}><option value="contains">Contains</option><option value="starts_with">Starts with</option><option value="exact">Exact match</option><option value="regex">Regular expression</option></select><ChevronDown size={15} /></span></label>
            <label>Priority<input type="number" min="0" value={draft.priority} onChange={(event) => change('priority', Number(event.target.value))} required /></label>
          </div>
          <label>Match value<input value={draft.match_value} onChange={(event) => change('match_value', event.target.value)} required maxLength={1000} placeholder={draft.match_type === 'regex' ? String.raw`Order (?P<order_no>\d+) dispatched` : 'Text to match'} /></label>
          <label>Outbound template<textarea value={draft.outbound_template} onChange={(event) => change('outbound_template', event.target.value)} required maxLength={1600} rows={3} placeholder="Your order {{order_ref}} is on its way." /></label>
          <div className="form-grid-two">
            <label>Sender ID<input value={draft.sender_id} onChange={(event) => change('sender_id', event.target.value.toUpperCase())} required maxLength={11} /></label>
            <label>Case matching<span className="select-wrap"><select value={draft.case_sensitive ? 'sensitive' : 'insensitive'} onChange={(event) => change('case_sensitive', event.target.value === 'sensitive')}><option value="insensitive">Ignore case</option><option value="sensitive">Case sensitive</option></select><ChevronDown size={15} /></span></label>
          </div>
          <label className="toggle-row"><span><strong>Rule enabled</strong><small>Disabled rules still claim matching messages.</small></span><input type="checkbox" checked={draft.is_enabled} onChange={(event) => change('is_enabled', event.target.checked)} /><span className="toggle-visual" /></label>
          {error && <p className="workspace-error" role="alert">{error}</p>}
          <div className="dialog-actions"><button className="secondary-button" type="button" onClick={onClose}>Cancel</button><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save rule'} <Check size={15} /></button></div>
        </form>
      </section>
    </div>
  )
}

function RuleHistoryPanel({ rule, canEdit, onClose, onRestored }: { rule: Rule; canEdit: boolean; onClose: () => void; onRestored: () => Promise<void> }) {
  const [versions, setVersions] = useState<RuleVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [restoring, setRestoring] = useState<number | null>(null)

  useEffect(() => {
    api<RuleVersion[]>(`/api/rules/${rule.id}/versions`).then(setVersions).catch((reason) => setError(reason instanceof Error ? reason.message : 'Unable to load rule history.')).finally(() => setLoading(false))
  }, [rule.id])

  async function restore(version: number) {
    setRestoring(version)
    setError('')
    try {
      await api(`/api/rules/${rule.id}/versions/${version}/restore`, { method: 'POST' })
      await onRestored()
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to restore this version.')
    } finally {
      setRestoring(null)
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="rule-dialog history-dialog" role="dialog" aria-modal="true" aria-labelledby="history-dialog-title">
        <div className="dialog-heading"><div><span className="section-kicker">VERSION HISTORY</span><h2 id="history-dialog-title">{rule.name}</h2></div><button className="quiet-icon" type="button" onClick={onClose} aria-label="Close"><X size={18} /></button></div>
        {error && <p className="workspace-error" role="alert">{error}</p>}
        {loading ? <p className="inline-instruction">Loading versions…</p> : (
          <div className="version-list">
            {versions.map((version) => (
              <div className="version-row" key={version.version}>
                <div><strong>v{version.version}</strong><small>{new Date(version.created_at).toLocaleString()}</small></div>
                <span className="template-preview">{String(version.snapshot.outbound_template ?? '')}</span>
                {canEdit && version.version !== rule.version && (
                  <button className="secondary-button compact-button" type="button" disabled={restoring !== null} onClick={() => void restore(version.version)}>
                    {restoring === version.version ? 'Restoring…' : 'Restore'}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function RulesPage({ canEdit }: { canEdit: boolean }) {
  const [rules, setRules] = useState<Rule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editor, setEditor] = useState<RuleDraft | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [historyRule, setHistoryRule] = useState<Rule | null>(null)
  const [sample, setSample] = useState('Order 4012 dispatched')
  const [recipient, setRecipient] = useState('254712345678')
  const [orderRef, setOrderRef] = useState('ORD-4012')
  const [result, setResult] = useState<TestResult | null>(null)
  const [testing, setTesting] = useState(false)

  async function loadRules() {
    setLoading(true)
    try {
      setRules(await api<Rule[]>('/api/rules'))
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load rules.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadRules() }, [])

  function startCreate() {
    setEditingId(null)
    setEditor({ ...emptyDraft, priority: (rules.at(-1)?.priority ?? 0) + 10 })
  }

  function startEdit(rule: Rule) {
    setEditingId(rule.id)
    const { id: _id, version: _version, ...draft } = rule
    setEditor(draft)
  }

  async function saveRule(draft: RuleDraft) {
    if (editingId === null) await api('/api/rules', { method: 'POST', body: JSON.stringify(draft) })
    else await api(`/api/rules/${editingId}`, { method: 'PATCH', body: JSON.stringify(draft) })
    await loadRules()
  }

  async function toggleRule(rule: Rule) {
    try {
      await api(`/api/rules/${rule.id}`, { method: 'PATCH', body: JSON.stringify({ is_enabled: !rule.is_enabled }) })
      await loadRules()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to update rule.')
    }
  }

  async function removeRule(rule: Rule) {
    if (!window.confirm(`Delete “${rule.name}”? Existing messages keep their rule history.`)) return
    try {
      await api(`/api/rules/${rule.id}`, { method: 'DELETE' })
      await loadRules()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to delete rule.')
    }
  }

  async function moveRule(index: number, offset: -1 | 1) {
    const destination = index + offset
    if (destination < 0 || destination >= rules.length) return
    const reordered = [...rules]
    ;[reordered[index], reordered[destination]] = [reordered[destination], reordered[index]]
    try {
      const saved = await api<Rule[]>('/api/rules/reorder', { method: 'PATCH', body: JSON.stringify({ rule_ids: reordered.map((rule) => rule.id) }) })
      setRules(saved)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to reorder rules.')
    }
  }

  async function testSample(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTesting(true)
    setError('')
    try {
      setResult(await api<TestResult>('/api/rules/test', {
        method: 'POST',
        body: JSON.stringify({ text: sample, recipient, order_ref: orderRef || null }),
      }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to test the message.')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="rules-page">
      <div className="page-heading">
        <div><div className="section-kicker">MESSAGE ROUTING / 02</div><h1>Notification rules</h1><p>Match inbound text to the right customer message.</p></div>
        {canEdit && <button className="primary-button add-rule-button" type="button" onClick={startCreate}><CirclePlus size={17} /> New rule</button>}
      </div>
      {error && <div className="workspace-alert" role="alert">{error}<button type="button" onClick={() => setError('')} aria-label="Dismiss"><X size={16} /></button></div>}

      <section className="rules-section">
        <div className="section-heading"><div><span className="section-kicker">PRIORITY ORDER</span><h2>Active rules <span>{rules.length}</span></h2></div><span className="section-meta">FIRST MATCH WINS</span></div>
        <div className="rules-table-wrap">
          <table className="rules-table">
            <thead><tr><th className="priority-column">ORDER</th><th>RULE</th><th>MATCH</th><th>SENDER</th><th>OUTBOUND TEMPLATE</th><th>STATUS</th>{canEdit && <th aria-label="Actions" />}</tr></thead>
            <tbody>
              {loading ? <tr><td className="table-empty" colSpan={canEdit ? 7 : 6}>Loading mapping rules…</td></tr> : rules.length === 0 ? <tr><td className="table-empty" colSpan={canEdit ? 7 : 6}>No rules created yet.</td></tr> : rules.map((rule, index) => (
                <tr key={rule.id}>
                  <td className="priority-cell"><span>{String(index + 1).padStart(2, '0')}</span>{canEdit && <div className="priority-arrows"><button type="button" title="Move up" disabled={index === 0} onClick={() => void moveRule(index, -1)}><ArrowUp size={13} /></button><button type="button" title="Move down" disabled={index === rules.length - 1} onClick={() => void moveRule(index, 1)}><ArrowDown size={13} /></button></div>}</td>
                  <td><div className="rule-name">{rule.name}<small>v{rule.version} · priority {rule.priority}</small></div></td>
                  <td><span className="match-chip">{rule.match_type}</span><small className="match-value">{rule.match_value}</small></td>
                  <td><span className="sender-chip">{rule.sender_id}</span></td>
                  <td><span className="template-preview">{rule.outbound_template}</span></td>
                  <td><button className={rule.is_enabled ? 'status-toggle enabled' : 'status-toggle'} type="button" disabled={!canEdit} onClick={() => void toggleRule(rule)} aria-label={`${rule.is_enabled ? 'Disable' : 'Enable'} ${rule.name}`}><span />{rule.is_enabled ? 'Enabled' : 'Disabled'}</button></td>
                  {canEdit && <td><div className="row-actions"><button className="quiet-icon" type="button" title="Version history" onClick={() => setHistoryRule(rule)}><History size={15} /></button><button className="quiet-icon" type="button" title="Edit rule" onClick={() => startEdit(rule)}><Pencil size={15} /></button><button className="quiet-icon danger-icon" type="button" title="Delete rule" onClick={() => void removeRule(rule)}><Trash2 size={15} /></button></div></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="test-section">
        <div className="test-heading"><span className="test-icon"><FlaskConical size={17} /></span><div><span className="section-kicker">RULE SIMULATOR</span><h2>Test a message</h2></div></div>
        <div className="test-grid">
          <form className="test-form" onSubmit={testSample}>
            <label>Service A text<textarea value={sample} onChange={(event) => setSample(event.target.value)} rows={3} required /></label>
            <div className="form-grid-two"><label>Recipient<input value={recipient} onChange={(event) => setRecipient(event.target.value)} /></label><label>Order reference<input value={orderRef} onChange={(event) => setOrderRef(event.target.value)} /></label></div>
            <button className="secondary-button simulate-button" type="submit" disabled={testing || !sample.trim()}>{testing ? 'Evaluating…' : 'Run simulation'} <ArrowDown size={15} /></button>
          </form>
          <div className={result ? 'test-result has-result' : 'test-result'}>
            {result ? <>
              <div className="result-top"><span className="section-kicker">RESULT</span><span className={`result-status ${result.status.toLowerCase()}`}>{result.status}</span></div>
              {result.rule && <div className="result-rule"><span>Matched rule</span><strong>{result.rule.name}</strong></div>}
              {result.rendered_text ? <div className="rendered-sms">{result.rendered_text}</div> : <div className="rendered-sms muted-result">No mapping rule matched this message.</div>}
              {result.rendered_text && <div className="result-meta"><span>{result.character_count} characters</span><span>{result.encoding}</span><strong>{result.segments} segment{result.segments === 1 ? '' : 's'}</strong></div>}
              {result.warnings.map((warning) => <p className="result-warning" key={warning}>{warning}</p>)}
            </> : <div className="result-placeholder"><span className="placeholder-spark" /><p>Rendered SMS and segment count will appear here.</p></div>}
          </div>
        </div>
      </section>
      {editor && <RuleEditor initial={editor} onClose={() => setEditor(null)} onSave={saveRule} />}
      {historyRule && <RuleHistoryPanel rule={historyRule} canEdit={canEdit} onClose={() => setHistoryRule(null)} onRestored={loadRules} />}
    </div>
  )
}

function UsersPage() {
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState({ name: '', email: '', role: 'operator' })
  const [showCreate, setShowCreate] = useState(false)
  const [saving, setSaving] = useState(false)

  async function loadUsers() {
    setLoading(true)
    try { setUsers(await api<ManagedUser[]>('/api/admin/users')); setError('') }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load users.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void loadUsers() }, [])

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true)
    try {
      await api('/api/admin/users', { method: 'POST', body: JSON.stringify(draft) })
      setDraft({ name: '', email: '', role: 'operator' }); setShowCreate(false); await loadUsers()
      setError('Invitation sent.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to send the invitation.') }
    finally { setSaving(false) }
  }

  async function updateUser(user: ManagedUser, changes: Partial<ManagedUser>) {
    try { await api(`/api/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify(changes) }); await loadUsers() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to update this user.') }
  }

  async function sendUserAction(user: ManagedUser, action: 'resend-invite' | 'force-password-reset' | 'revoke-sessions') {
    try {
      await api(`/api/admin/users/${user.id}/${action}`, { method: 'POST' })
      setError(action === 'revoke-sessions' ? `Sessions revoked for ${user.name}.` : `Email sent to ${user.email}.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to complete the request.') }
  }

  return (
    <div className="account-page">
      <div className="page-heading"><div><div className="section-kicker">ACCESS CONTROL / 03</div><h1>Team members</h1><p>Invite colleagues and manage their workspace access.</p></div><button className="primary-button" type="button" onClick={() => setShowCreate((value) => !value)}><CirclePlus size={16} /> Invite user</button></div>
      {error && <div className="workspace-alert" role="status">{error}<button type="button" onClick={() => setError('')} aria-label="Dismiss"><X size={16} /></button></div>}
      {showCreate && <form className="invite-form" onSubmit={createUser}><label>Name<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label><label>Email<input type="email" value={draft.email} onChange={(event) => setDraft({ ...draft, email: event.target.value })} required /></label><label>Role<select value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value })}><option value="operator">Operator</option><option value="viewer">Viewer</option><option value="super_admin">Super Admin</option></select></label><button className="primary-button" disabled={saving}>{saving ? 'Sending…' : 'Send invite'} <ArrowDown size={15} /></button></form>}
      <div className="section-heading"><div><span className="section-kicker">WORKSPACE ACCESS</span><h2>Users <span>{users.length}</span></h2></div></div>
      <div className="users-table-wrap"><table className="users-table"><thead><tr><th>PERSON</th><th>ROLE</th><th>ACCOUNT</th><th>ACCESS</th><th>MANAGE</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={5} className="table-empty">Loading users…</td></tr> : users.map((managedUser) => <tr key={managedUser.id}>
          <td><div className="managed-person"><span className="managed-avatar">{managedUser.name.slice(0, 1).toUpperCase()}</span><span><strong>{managedUser.name}</strong><small>{managedUser.email}</small></span></div></td>
          <td><select className="role-select" value={managedUser.role} onChange={(event) => void updateUser(managedUser, { role: event.target.value })}><option value="super_admin">Super Admin</option><option value="operator">Operator</option><option value="viewer">Viewer</option></select></td>
          <td><span className={managedUser.password_set ? 'account-state active' : 'account-state pending'}><i />{managedUser.password_set ? 'Password set' : 'Invite pending'}</span></td>
          <td><button className={managedUser.is_active ? 'status-toggle enabled' : 'status-toggle'} type="button" onClick={() => void updateUser(managedUser, { is_active: !managedUser.is_active })}><span />{managedUser.is_active ? 'Active' : 'Inactive'}</button></td>
          <td><div className="user-actions">{!managedUser.password_set ? <button className="secondary-button compact-button" type="button" onClick={() => void sendUserAction(managedUser, 'resend-invite')}>Resend invite</button> : <button className="quiet-icon" type="button" title="Send password reset link" onClick={() => void sendUserAction(managedUser, 'force-password-reset')}><KeyRound size={15} /></button>}<button className="quiet-icon" type="button" title="Revoke all sessions" onClick={() => void sendUserAction(managedUser, 'revoke-sessions')}><LogOut size={15} /></button></div></td>
        </tr>)}
      </tbody></table></div>
    </div>
  )
}

function AccountPage({ user, onUserUpdated }: { user: User; onUserUpdated: (user: User) => void }) {
  const [name, setName] = useState(user.name)
  const [sessions, setSessions] = useState<ActiveSession[]>([])
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [challengeToken, setChallengeToken] = useState('')
  const [code, setCode] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  async function loadSessions() { setSessions(await api<ActiveSession[]>('/api/me/sessions')) }
  useEffect(() => { void loadSessions().catch((reason) => setError(reason instanceof Error ? reason.message : 'Unable to load sessions.')) }, [])

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    try {
      const updated = await api<User>('/api/me', { method: 'PATCH', body: JSON.stringify({ name }) })
      onUserUpdated(updated); setNotice('Profile updated.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to update profile.') }
  }

  async function startPasswordChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    try {
      const response = await api<{ challenge_token: string }>('/api/me/password/change/request-otp', {
        method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword, confirm_password: confirmPassword }),
      })
      setChallengeToken(response.challenge_token); setNotice('A confirmation code has been emailed to you.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to start password change.') }
  }

  async function confirmPasswordChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      await api('/api/me/password/change/confirm', { method: 'POST', body: JSON.stringify({ challenge_token: challengeToken, code }) })
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword(''); setChallengeToken(''); setCode('')
      setNotice('Password changed. Other active sessions have been signed out.')
      await loadSessions()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The code could not be verified.') }
  }

  async function revokeSession(session: ActiveSession) {
    try {
      await api(`/api/me/sessions/${session.id}`, { method: 'DELETE' })
      if (session.current) { window.location.reload(); return }
      await loadSessions()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to revoke this session.') }
  }

  return (
    <div className="account-page">
      <div className="page-heading"><div><div className="section-kicker">PERSONAL SETTINGS / 03</div><h1>My account</h1><p>Manage your profile, password, and signed-in devices.</p></div></div>
      {(notice || error) && <div className={error ? 'workspace-alert' : 'workspace-notice'} role="status">{error || notice}<button type="button" onClick={() => { setError(''); setNotice('') }} aria-label="Dismiss"><X size={16} /></button></div>}
      <div className="account-grid">
        <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">PROFILE</span><h2>Account details</h2></div></div><form className="settings-form" onSubmit={saveProfile}><label>Display name<input value={name} onChange={(event) => setName(event.target.value)} required /></label><label>Email address<input value={user.email} disabled /></label><div className="settings-form-footer"><span className="account-state active"><i />{user.role.replace('_', ' ')}</span><button className="primary-button" type="submit">Save changes <Check size={15} /></button></div></form></section>
        <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">SECURITY</span><h2>Change password</h2></div></div>{challengeToken ? <form className="settings-form" onSubmit={confirmPasswordChange}><p className="inline-instruction">Enter the code sent to your email to confirm this change.</p><label>6-digit code<input value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" required /></label><button className="primary-button" type="submit" disabled={code.length !== 6}>Confirm password change <Check size={15} /></button></form> : <form className="settings-form" onSubmit={startPasswordChange}><label>Current password<input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label><label>New password<input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required minLength={12} /></label><label>Confirm new password<input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required minLength={12} /></label><button className="secondary-button" type="submit">Send confirmation code <ArrowDown size={15} /></button></form>}</section>
      </div>
      <section className="settings-section sessions-section"><div className="section-heading"><div><span className="section-kicker">ACTIVE DEVICES</span><h2>Signed-in sessions <span>{sessions.length}</span></h2></div></div><div className="session-list">{sessions.map((session) => <div className="session-item" key={session.id}><span className="session-device"><UserRound size={17} /></span><span className="session-details"><strong>{session.device}</strong><small>{session.ip_address ?? 'IP unavailable'} · {new Date(session.last_seen_at).toLocaleString()}</small></span>{session.current && <span className="current-session">THIS DEVICE</span>}<button className="quiet-icon danger-icon" type="button" title="Revoke session" onClick={() => void revokeSession(session)}><X size={16} /></button></div>)}{sessions.length === 0 && <p className="empty-sessions">No active sessions.</p>}</div></section>
    </div>
  )
}

function BlocklistPage() {
  const [entries, setEntries] = useState<BlockedNumber[]>([])
  const [phone, setPhone] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function loadEntries() {
    try { setEntries(await api<BlockedNumber[]>('/api/blocklist')) }
    catch (issue) { setError(issue instanceof Error ? issue.message : 'Unable to load the blocklist.') }
  }
  useEffect(() => { void loadEntries() }, [])

  async function addNumber(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError('')
    try {
      await api('/api/blocklist', { method: 'POST', body: JSON.stringify({ phone_number: phone, reason: reason || null }) })
      setPhone(''); setReason(''); await loadEntries()
    } catch (issue) { setError(issue instanceof Error ? issue.message : 'Unable to block this number.') }
    finally { setSaving(false) }
  }

  async function removeEntry(entry: BlockedNumber) {
    try { await api(`/api/blocklist/${entry.id}`, { method: 'DELETE' }); await loadEntries() }
    catch (issue) { setError(issue instanceof Error ? issue.message : 'Unable to remove this number.') }
  }

  return <div className="account-page"><div className="page-heading"><div><div className="section-kicker">CUSTOMER SAFETY / 04</div><h1>Blocklist</h1><p>Keep opted-out and restricted numbers out of delivery.</p></div></div>{error && <div className="workspace-alert" role="alert">{error}<button type="button" onClick={() => setError('')} aria-label="Dismiss"><X size={16} /></button></div>}<form className="blocklist-form" onSubmit={addNumber}><label>Kenyan mobile number<input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="0712 345 678" required /></label><label>Reason<input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={255} placeholder="Customer opt-out" /></label><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Adding…' : 'Block number'} <Ban size={15} /></button></form><div className="section-heading"><div><span className="section-kicker">DO NOT SEND</span><h2>Blocked numbers <span>{entries.length}</span></h2></div></div><div className="users-table-wrap"><table className="users-table blocklist-table"><thead><tr><th>PHONE NUMBER</th><th>REASON</th><th>ADDED</th><th /></tr></thead><tbody>{entries.length === 0 ? <tr><td className="table-empty" colSpan={4}>No blocked numbers.</td></tr> : entries.map((entry) => <tr key={entry.id}><td className="message-phone">{entry.phone_number}</td><td>{entry.reason ?? '—'}</td><td>{new Date(entry.created_at).toLocaleDateString()}</td><td><button className="quiet-icon" type="button" title="Unblock number" onClick={() => void removeEntry(entry)}><X size={15} /></button></td></tr>)}</tbody></table></div></div>
}

function SettingsPage() {
  const [config, setConfig] = useState<Configuration | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [slackWebhook, setSlackWebhook] = useState('')
  const [telegramToken, setTelegramToken] = useState('')
  const [allowedSenders, setAllowedSenders] = useState('UPENFLOW')
  const [testAllowlist, setTestAllowlist] = useState('')
  const [alertEmails, setAlertEmails] = useState('')
  const [networkPrefixes, setNetworkPrefixes] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  function applyConfig(value: Configuration) {
    setConfig(value)
    setAllowedSenders(value.gateway.allowed_sender_ids.join(', '))
    setTestAllowlist(value.safety.test_allowlist.join(', '))
    setAlertEmails(value.alert_emails.join(', '))
    setNetworkPrefixes(Object.fromEntries(Object.entries(value.network_prefixes).map(([network, prefixes]) => [network, prefixes.join(', ')])))
  }

  useEffect(() => {
    api<Configuration>('/api/settings').then(applyConfig).catch((reason) => setError(reason instanceof Error ? reason.message : 'Unable to load settings.'))
  }, [])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!config) return
    setSaving(true); setError(''); setNotice('')
    const senders = allowedSenders.split(',').map((value) => value.trim().toUpperCase()).filter(Boolean)
    const gateway = {
      base_url: config.gateway.base_url || null,
      username: config.gateway.username || null,
      default_sender_id: config.gateway.default_sender_id,
      allowed_sender_ids: senders,
      ...(apiKey ? { api_key: apiKey } : {}),
    }
    const monitoring = {
      ...config.monitoring,
      ...(slackWebhook ? { slack_webhook_url: slackWebhook } : {}),
      ...(telegramToken ? { telegram_bot_token: telegramToken } : {}),
    }
    const network_prefixes = Object.fromEntries(
      Object.entries(networkPrefixes).map(([network, value]) => [network, value.split(',').map((prefix) => prefix.trim()).filter(Boolean)])
    )
    try {
      const updated = await api<Configuration>('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({
          billing: config.billing, gateway, limits: config.limits,
          safety: { ...config.safety, test_allowlist: testAllowlist.split(',').map((number) => number.trim()).filter(Boolean) },
          quiet_hours: config.quiet_hours, retention: config.retention, monitoring, network_prefixes,
          alert_emails: alertEmails.split(',').map((email) => email.trim()).filter(Boolean),
          timezone: config.timezone,
        }),
      })
      applyConfig(updated); setApiKey(''); setSlackWebhook(''); setTelegramToken(''); setNotice('Settings saved and audit-logged.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save settings.') }
    finally { setSaving(false) }
  }

  if (!config) return <div className="account-page"><div className="dashboard-loading">Loading settings…</div>{error && <div className="workspace-alert">{error}</div>}</div>
  const updateBilling = (key: keyof Configuration['billing'], value: string | number) => setConfig({ ...config, billing: { ...config.billing, [key]: value } })
  const updateGateway = (key: 'base_url' | 'username' | 'default_sender_id', value: string) => setConfig({ ...config, gateway: { ...config.gateway, [key]: value } })
  const updateLimits = (key: keyof Configuration['limits'], value: number) => setConfig({ ...config, limits: { ...config.limits, [key]: value } })
  const updateSafety = (key: keyof Configuration['safety'], value: number | boolean) => setConfig({ ...config, safety: { ...config.safety, [key]: value } })
  const updateQuietHours = (key: keyof Configuration['quiet_hours'], value: string | boolean) => setConfig({ ...config, quiet_hours: { ...config.quiet_hours, [key]: value } })
  const updateRetention = (key: keyof Configuration['retention'], value: number) => setConfig({ ...config, retention: { ...config.retention, [key]: value } })
  const updateMonitoring = (key: 'service_a_silence_minutes' | 'error_rate_threshold_percent' | 'low_credit_kes' | 'telegram_chat_id' | 'oncall_phone', value: string | number) => setConfig({ ...config, monitoring: { ...config.monitoring, [key]: value } })

  return <div className="account-page settings-page"><div className="page-heading"><div><div className="section-kicker">SYSTEM / 05</div><h1>Settings</h1><p>Configure billing, gateway access, and message limits.</p></div></div>{(notice || error) && <div className={error ? 'workspace-alert' : 'workspace-notice'} role="status">{error || notice}<button type="button" onClick={() => { setError(''); setNotice('') }} aria-label="Dismiss"><X size={16} /></button></div>}<form onSubmit={save}>
    <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">BILLING</span><h2>SMS costs</h2></div></div><div className="settings-grid"><label>Cost per SMS segment<input type="number" min="0" step="0.01" value={config.billing.cost_per_segment_kes} onChange={(event) => updateBilling('cost_per_segment_kes', event.target.value)} /></label><label>Currency<input maxLength={3} value={config.billing.currency} onChange={(event) => updateBilling('currency', event.target.value.toUpperCase())} /></label><label>Monthly budget<input type="number" min="0" step="0.01" value={config.billing.monthly_budget_kes} onChange={(event) => updateBilling('monthly_budget_kes', event.target.value)} /></label><label>Budget alert threshold (%)<input type="number" min="1" max="100" value={config.billing.alert_threshold_percent} onChange={(event) => updateBilling('alert_threshold_percent', Number(event.target.value))} /></label></div></section>
    <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">SERVICE B</span><h2>Gateway connection</h2></div></div><div className="settings-grid"><label>Base URL<input type="url" value={config.gateway.base_url ?? ''} onChange={(event) => updateGateway('base_url', event.target.value)} placeholder="https://gateway.example.com" /></label><label>Username<input value={config.gateway.username ?? ''} onChange={(event) => updateGateway('username', event.target.value)} /></label><label>Default Sender ID<input value={config.gateway.default_sender_id} onChange={(event) => updateGateway('default_sender_id', event.target.value.toUpperCase())} maxLength={11} /></label><label>Allowed Sender IDs<input value={allowedSenders} onChange={(event) => setAllowedSenders(event.target.value)} placeholder="UPENFLOW, UPENFLOW2" /><small>Separate registered IDs with commas.</small></label><label className="secret-field">API key <span>{config.gateway.has_api_key ? 'Saved key is masked' : 'No key saved'}</span><input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={config.gateway.has_api_key ? 'Enter a new key to rotate' : 'Enter gateway API key'} /></label></div><p className="inline-instruction">Service A and Service B credentials will be supplied once the real gateway is connected; these fields accept them without a redeploy.</p></section>
    <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">DELIVERY LIMITS</span><h2>Queue and retries</h2></div></div><div className="settings-grid"><label>Send rate (SMS/second)<input type="number" min="1" value={config.limits.send_rate_per_second} onChange={(event) => updateLimits('send_rate_per_second', Number(event.target.value))} /></label><label>Maximum segments<input type="number" min="1" max="3" value={config.limits.max_segments} onChange={(event) => updateLimits('max_segments', Number(event.target.value))} /></label><label>Stale queue cutoff (minutes)<input type="number" min="1" value={config.limits.stale_queue_minutes} onChange={(event) => updateLimits('stale_queue_minutes', Number(event.target.value))} /></label><label>Retry attempts<input type="number" min="1" max="10" value={config.limits.retry_attempts} onChange={(event) => updateLimits('retry_attempts', Number(event.target.value))} /></label><label>Timezone<input value={config.timezone} onChange={(event) => setConfig({ ...config, timezone: event.target.value })} /></label></div></section>
    <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">CUSTOMER SAFEGUARDS</span><h2>Throttle and test mode</h2></div></div><div className="settings-grid"><label>Maximum SMS per recipient / hour<input type="number" min="1" value={config.safety.max_per_recipient_hour} onChange={(event) => updateSafety('max_per_recipient_hour', Number(event.target.value))} /></label><label>Duplicate content window (minutes)<input type="number" min="1" value={config.safety.duplicate_window_minutes} onChange={(event) => updateSafety('duplicate_window_minutes', Number(event.target.value))} /></label><label className="config-toggle"><span><strong>Test mode</strong><small>Only send to allowlisted numbers.</small></span><input type="checkbox" checked={config.safety.test_mode} onChange={(event) => updateSafety('test_mode', event.target.checked)} /></label><label className="config-toggle"><span><strong>Fake gateway</strong><small>Record test sends without delivery.</small></span><input type="checkbox" checked={config.safety.fake_gateway} onChange={(event) => updateSafety('fake_gateway', event.target.checked)} /></label><label className="wide-setting">Test number allowlist<input value={testAllowlist} onChange={(event) => setTestAllowlist(event.target.value)} placeholder="0712345678, 254110123456" /><small>Only Kenyan mobile numbers are accepted.</small></label></div></section>
    <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">QUIET HOURS</span><h2>Hold sends overnight</h2></div></div><div className="settings-grid"><label className="config-toggle"><span><strong>Enable quiet hours</strong><small>Queue messages during the window below.</small></span><input type="checkbox" checked={config.quiet_hours.enabled} onChange={(event) => updateQuietHours('enabled', event.target.checked)} /></label><label>Start (HH:MM, local time)<input value={config.quiet_hours.start} onChange={(event) => updateQuietHours('start', event.target.value)} placeholder="21:00" /></label><label>End (HH:MM, local time)<input value={config.quiet_hours.end} onChange={(event) => updateQuietHours('end', event.target.value)} placeholder="07:00" /></label></div></section>
    <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">DATA RETENTION</span><h2>Automatic cleanup</h2></div></div><div className="settings-grid"><label>Message retention (days)<input type="number" min="1" value={config.retention.message_retention_days} onChange={(event) => updateRetention('message_retention_days', Number(event.target.value))} /></label><label>Audit log retention (days)<input type="number" min="1" value={config.retention.audit_log_retention_days} onChange={(event) => updateRetention('audit_log_retention_days', Number(event.target.value))} /></label></div></section>
    <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">MONITORING &amp; ALERTS</span><h2>Who gets paged</h2></div></div><div className="settings-grid"><label className="wide-setting">Alert emails<input value={alertEmails} onChange={(event) => setAlertEmails(event.target.value)} placeholder="ops@upenflow.co.ke, oncall@upenflow.co.ke" /></label><label>Service A silence alert (minutes)<input type="number" min="1" value={config.monitoring.service_a_silence_minutes} onChange={(event) => updateMonitoring('service_a_silence_minutes', Number(event.target.value))} /></label><label>Service B error-rate threshold (%)<input type="number" min="1" max="100" value={config.monitoring.error_rate_threshold_percent} onChange={(event) => updateMonitoring('error_rate_threshold_percent', Number(event.target.value))} /></label><label>Low credit threshold (KES)<input type="number" min="0" value={config.monitoring.low_credit_kes} onChange={(event) => updateMonitoring('low_credit_kes', event.target.value)} /></label><label>On-call SMS number<input value={config.monitoring.oncall_phone ?? ''} onChange={(event) => updateMonitoring('oncall_phone', event.target.value)} placeholder="0712345678" /></label><label className="secret-field">Slack webhook <span>{config.monitoring.has_slack_webhook ? 'Saved webhook is masked' : 'Not configured'}</span><input type="password" autoComplete="new-password" value={slackWebhook} onChange={(event) => setSlackWebhook(event.target.value)} placeholder={config.monitoring.has_slack_webhook ? 'Enter a new URL to rotate' : 'https://hooks.slack.com/...'} /></label><label className="secret-field">Telegram bot token <span>{config.monitoring.has_telegram_bot_token ? 'Saved token is masked' : 'Not configured'}</span><input type="password" autoComplete="new-password" value={telegramToken} onChange={(event) => setTelegramToken(event.target.value)} placeholder={config.monitoring.has_telegram_bot_token ? 'Enter a new token to rotate' : 'Bot token'} /></label><label>Telegram chat ID<input value={config.monitoring.telegram_chat_id ?? ''} onChange={(event) => updateMonitoring('telegram_chat_id', event.target.value)} /></label></div></section>
    <section className="settings-section"><div className="section-heading"><div><span className="section-kicker">NETWORK PREFIXES</span><h2>Carrier detection table</h2></div></div><div className="settings-grid">{Object.entries(networkPrefixes).map(([network, value]) => <label className="wide-setting" key={network}>{network} prefixes<input value={value} onChange={(event) => setNetworkPrefixes({ ...networkPrefixes, [network]: event.target.value })} /></label>)}</div></section>
    <div className="settings-save-row"><span>Changes are recorded in the audit log.</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save settings'} <Check size={15} /></button></div>
  </form></div>
}

function SendingBanner({ isAdmin }: { isAdmin: boolean }) {
  const [sending, setSending] = useState<SendingState>({ state: 'on', queued_count: 0, test_mode: false })
  const [target, setTarget] = useState<'on' | 'paused' | 'stopped' | null>(null)
  const [reason, setReason] = useState('')
  const [resumePolicy, setResumePolicy] = useState<'send_recent' | 'send_all' | 'discard_all'>('send_recent')
  const [staleMinutes, setStaleMinutes] = useState(60)
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function refresh() {
    try { setSending(await api<SendingState>('/api/settings/sending')) }
    catch { return }
  }
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => window.clearInterval(timer)
  }, [])

  async function save() {
    if (!target || !confirmed || reason.trim().length < 3) return
    setSaving(true); setError('')
    try {
      const result = await api<SendingState>('/api/settings/sending', {
        method: 'PUT',
        body: JSON.stringify({
          state: target, confirmed, reason,
          ...(sending.state === 'paused' && target === 'on' ? { resume_policy: resumePolicy, stale_minutes: staleMinutes } : {}),
        }),
      })
      setSending(result); setTarget(null); setReason(''); setConfirmed(false)
    } catch (reasonError) { setError(reasonError instanceof Error ? reasonError.message : 'Unable to change sending state.') }
    finally { setSaving(false) }
  }

  return <>
    <div className={`workspace-banner state-${sending.state}${sending.test_mode ? ' test-mode' : ''}`}>
      <span className="sending-state-label"><i /> SENDING {sending.state.toUpperCase()}{sending.test_mode && <strong className="test-mode-tag">TEST MODE</strong>}</span>
      <span className="sending-queue-count">{sending.queued_count} QUEUED <i>·</i> NAIROBI</span>
      {isAdmin && <div className="sending-controls">{sending.state === 'on' ? <><button type="button" onClick={() => { setTarget('paused'); setConfirmed(false) }}><Pause size={13} /> Pause</button><button type="button" onClick={() => { setTarget('stopped'); setConfirmed(false) }}><Square size={12} /> Stop</button></> : <button type="button" onClick={() => { setTarget('on'); setConfirmed(false) }}><Play size={13} /> Resume</button>}</div>}
    </div>
    {target && <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setTarget(null) }}><section className="switch-dialog" role="dialog" aria-modal="true" aria-labelledby="switch-title"><div className="dialog-heading"><div><span className="section-kicker">GLOBAL SEND CONTROL</span><h2 id="switch-title">{target === 'on' ? 'Resume sending' : target === 'paused' ? 'Pause sending' : 'Stop sending'}</h2></div><button className="quiet-icon" type="button" onClick={() => setTarget(null)} aria-label="Close"><X size={18} /></button></div><p className="switch-description">{target === 'on' && sending.state === 'paused' ? `${sending.queued_count} messages are queued. Choose how to handle them before resuming.` : 'This change applies to new inbound messages and is recorded in the audit log.'}</p>{target === 'on' && sending.state === 'paused' && <div className="resume-choice"><label><input type="radio" name="resume-policy" checked={resumePolicy === 'send_recent'} onChange={() => setResumePolicy('send_recent')} /><span><strong>Send recent messages</strong><small>Skip messages older than the cutoff.</small></span></label>{resumePolicy === 'send_recent' && <label className="cutoff-input">Cutoff in minutes<input type="number" min="1" max="10080" value={staleMinutes} onChange={(event) => setStaleMinutes(Number(event.target.value))} /></label>}<label><input type="radio" name="resume-policy" checked={resumePolicy === 'send_all'} onChange={() => setResumePolicy('send_all')} /><span><strong>Send all queued</strong><small>Includes older fulfilment updates.</small></span></label><label><input type="radio" name="resume-policy" checked={resumePolicy === 'discard_all'} onChange={() => setResumePolicy('discard_all')} /><span><strong>Discard all queued</strong><small>Mark queued messages as skipped.</small></span></label></div>}<label className="reason-field">Reason for this change<textarea value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} maxLength={255} rows={2} placeholder="e.g. Gateway maintenance" required /></label><label className="confirm-switch"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I understand this will change message handling.</span></label>{error && <p className="workspace-error" role="alert">{error}</p>}<div className="dialog-actions"><button className="secondary-button" type="button" onClick={() => setTarget(null)}>Cancel</button><button className="primary-button" type="button" disabled={saving || !confirmed || reason.trim().length < 3} onClick={() => void save()}>{saving ? 'Applying…' : 'Confirm change'} <Check size={15} /></button></div></section></div>}
  </>
}

function NotificationsPage({ canExport }: { canExport: boolean }) {
  const initialParams = new URLSearchParams(window.location.search)
  const [search, setSearch] = useState(initialParams.get('search') ?? '')
  const [status, setStatus] = useState(initialParams.get('status') ?? '')
  const [network, setNetwork] = useState(initialParams.get('network') ?? '')
  const [senderId, setSenderId] = useState(initialParams.get('sender_id') ?? '')
  const [fromDate, setFromDate] = useState(initialParams.get('from_date') ?? '')
  const [toDate, setToDate] = useState(initialParams.get('to_date') ?? '')
  const [page, setPage] = useState(Number(initialParams.get('page') ?? 1))
  const [items, setItems] = useState<Message[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<MessageDetail | null>(null)
  const [timelinePhone, setTimelinePhone] = useState<{ phone_number: string; messages: Message[] } | null>(null)
  const [resending, setResending] = useState(false)

  function filterParams() {
    const params = new URLSearchParams({ page: String(page) })
    if (search.trim()) params.set('search', search.trim())
    if (status) params.set('status', status)
    if (network) params.set('network', network)
    if (senderId.trim()) params.set('sender_id', senderId.trim())
    if (fromDate) params.set('from_date', fromDate)
    if (toDate) params.set('to_date', toDate)
    return params
  }

  async function loadMessages() {
    setLoading(true)
    const params = filterParams()
    const url = new URL(window.location.href)
    url.search = params.toString()
    window.history.replaceState({}, '', url)
    try {
      const result = await api<{ items: Message[]; total: number; pages: number }>(`/api/messages?${params}`)
      setItems(result.items); setTotal(result.total); setPages(result.pages); setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load notifications.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void loadMessages() }, [page, status, network])

  async function openMessage(message: Message) {
    try { setSelected(await api<MessageDetail>(`/api/messages/${message.id}`)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load message details.') }
  }

  async function viewTimeline(phone: string) {
    try { setTimelinePhone(await api<{ phone_number: string; messages: Message[] }>(`/api/customers/${encodeURIComponent(phone)}/timeline`)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load this customer’s history.') }
  }

  async function resend(message: MessageDetail) {
    setResending(true)
    try {
      await api(`/api/messages/${message.id}/resend`, { method: 'POST' })
      setSelected(await api<MessageDetail>(`/api/messages/${message.id}`))
      setNotice('Message requeued for sending.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to resend this message.') }
    finally { setResending(false) }
  }

  function copyId(value: string) {
    navigator.clipboard?.writeText(value).then(() => setNotice('Copied to clipboard.')).catch(() => undefined)
  }

  return (
    <div className="messages-page">
      <div className="page-heading"><div><div className="section-kicker">MESSAGE ACTIVITY / 07</div><h1>Notifications</h1><p>Search fulfilment messages and inspect their routing result.</p></div>{canExport && <a className="secondary-button export-button" href={`/api/messages/export.csv?${filterParams()}`}><Download size={15} /> Export CSV</a>}</div>
      {error && <div className="workspace-alert" role="alert">{error}<button type="button" onClick={() => setError('')} aria-label="Dismiss"><X size={16} /></button></div>}
      {notice && <div className="workspace-notice" role="status">{notice}<button type="button" onClick={() => setNotice('')} aria-label="Dismiss"><X size={16} /></button></div>}
      <div className="message-toolbar"><form className="message-search" onSubmit={(event) => { event.preventDefault(); setPage(1); void loadMessages() }}><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Phone, order ref, message ID, or text" /><button type="submit">Search</button></form><label className="filter-select"><span>Status</span><select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }}><option value="">All statuses</option>{['Queued', 'Unmapped', 'Suppressed', 'Skipped', 'Invalid recipient', 'Sent', 'Delivered', 'Failed', 'Throttled', 'Blocked'].map((value) => <option key={value}>{value}</option>)}</select><ChevronDown size={14} /></label><label className="filter-select"><span>Network</span><select value={network} onChange={(event) => { setNetwork(event.target.value); setPage(1) }}><option value="">All networks</option>{['Safaricom', 'Airtel', 'Telkom'].map((value) => <option key={value}>{value}</option>)}</select><ChevronDown size={14} /></label><span className="result-count">{total.toLocaleString()} messages</span></div>
      <div className="message-toolbar message-toolbar-secondary"><label className="filter-select"><span>Sender ID</span><input value={senderId} onChange={(event) => setSenderId(event.target.value)} placeholder="UPENFLOW" /></label><label className="filter-select"><span>From</span><input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} /></label><label className="filter-select"><span>To</span><input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} /></label><button className="secondary-button compact-button" type="button" onClick={() => { setPage(1); void loadMessages() }}>Apply filters</button>{search.trim() && normalizeDisplayPhone(search) && <button className="secondary-button compact-button" type="button" onClick={() => void viewTimeline(search.trim())}><Clock size={13} /> Customer timeline</button>}</div>
      <div className="messages-table-wrap"><table className="messages-table"><thead><tr><th>TIME</th><th>RECIPIENT</th><th>ORDER REF</th><th>MESSAGE</th><th>NETWORK</th><th>SEGS · COST</th><th>STATUS</th></tr></thead><tbody>
        {loading ? <tr><td className="table-empty" colSpan={7}>Loading notifications…</td></tr> : items.length === 0 ? <tr><td className="table-empty" colSpan={7}>No notifications match these filters.</td></tr> : items.map((message) => <tr key={message.id} onClick={() => void openMessage(message)} tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter') void openMessage(message) }}><td className="message-time">{new Date(message.received_at).toLocaleString()}</td><td className="message-phone">{message.recipient}</td><td>{message.order_ref ?? '—'}</td><td><span className="message-preview">{message.sms_preview ?? message.inbound_preview}</span></td><td>{message.network ?? '—'}</td><td>{message.segments ? `${message.segments} · KES ${message.cost_kes?.toFixed(2) ?? '0.00'}` : '—'}</td><td><span className={`message-status status-${message.status.toLowerCase().replaceAll(' ', '-')}`}>{message.status}</span></td></tr>)}
      </tbody></table></div>
      <div className="table-pagination"><span>Page {pages ? page : 0} of {pages}</span><div><button className="quiet-icon" type="button" disabled={page <= 1} title="Previous page" onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={17} /></button><button className="quiet-icon" type="button" disabled={!pages || page >= pages} title="Next page" onClick={() => setPage((value) => value + 1)}><ChevronRight size={17} /></button></div></div>
      {selected && <div className="detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null) }}><aside className="message-drawer" role="dialog" aria-modal="true" aria-label="Notification details">
        <div className="drawer-heading"><div><span className="section-kicker">MESSAGE DETAIL</span><h2>{selected.order_ref ?? selected.message_id}</h2></div><button className="quiet-icon" type="button" onClick={() => setSelected(null)} aria-label="Close"><X size={18} /></button></div>
        <span className={`message-status status-${selected.status.toLowerCase().replaceAll(' ', '-')}`}>{selected.status}</span>
        <dl className="message-metadata">
          <div><dt>Received</dt><dd>{new Date(selected.received_at).toLocaleString()}</dd></div>
          <div><dt>Recipient</dt><dd>{selected.recipient}</dd></div>
          <div><dt>Source message ID</dt><dd>{selected.message_id} <button className="quiet-icon copy-icon" type="button" title="Copy message ID" onClick={() => copyId(selected.message_id)}>⧉</button></dd></div>
          <div><dt>Rule version</dt><dd>{selected.rule ? `${selected.rule} · v${selected.rule_version}` : 'No rule matched'}</dd></div>
          <div><dt>Sender ID</dt><dd>{selected.sender_id ?? '—'}</dd></div>
          <div><dt>Network</dt><dd>{selected.network ?? '—'}</dd></div>
          <div><dt>Segments · cost</dt><dd>{selected.segments ?? '—'} · KES {selected.cost_kes?.toFixed(2) ?? '0.00'}</dd></div>
          <div><dt>Provider message ID</dt><dd>{selected.provider_message_id ?? '—'}</dd></div>
          <div><dt>Attempts</dt><dd>{selected.attempts}</dd></div>
        </dl>
        <section className="drawer-message"><span className="section-kicker">STATUS TIMELINE</span><div className="timeline-list">{selected.timeline.map((event, index) => <div className="timeline-row" key={index}><span className="timeline-dot" /><strong>{event.status}</strong>{event.at && <small>{new Date(event.at).toLocaleString()}</small>}</div>)}</div></section>
        <section className="drawer-message"><span className="section-kicker">SERVICE A TEXT</span><p>{selected.inbound_text}</p></section>
        <section className="drawer-message"><span className="section-kicker">RENDERED SMS</span><p>{selected.rendered_text ?? 'No outbound message was created.'}</p></section>
        {selected.status_reason && <p className="drawer-reason">{selected.status_reason}</p>}
        {selected.error && <p className="drawer-reason">Gateway error: {selected.error}</p>}
        <div className="drawer-actions">
          {selected.can_resend && <button className="primary-button" type="button" disabled={resending} onClick={() => void resend(selected)}><RefreshCw size={14} /> {resending ? 'Resending…' : 'Resend'}</button>}
          <button className="secondary-button compact-button" type="button" onClick={() => void viewTimeline(selected.recipient)}><Clock size={13} /> Customer timeline</button>
        </div>
        <a className="drawer-source" href={`/api/messages/${selected.id}`} target="_blank" rel="noreferrer">Open message data <ArrowUpRight size={14} /></a>
      </aside></div>}
      {timelinePhone && <div className="detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setTimelinePhone(null) }}><aside className="message-drawer" role="dialog" aria-modal="true" aria-label="Customer timeline">
        <div className="drawer-heading"><div><span className="section-kicker">CUSTOMER TIMELINE</span><h2>{timelinePhone.phone_number}</h2></div><button className="quiet-icon" type="button" onClick={() => setTimelinePhone(null)} aria-label="Close"><X size={18} /></button></div>
        <div className="timeline-list">{timelinePhone.messages.length === 0 ? <p className="inline-instruction">No messages found for this number.</p> : timelinePhone.messages.map((message) => <div className="timeline-row" key={message.id}><span className="timeline-dot" /><strong>{message.status}</strong><small>{new Date(message.received_at).toLocaleString()} · {message.sms_preview ?? message.inbound_preview}</small></div>)}</div>
      </aside></div>}
    </div>
  )
}

function normalizeDisplayPhone(value: string): boolean {
  const digits = value.replace(/[\s()+-]/g, '')
  return /^(0\d{9}|\d{9}|254\d{9})$/.test(digits)
}

function changeTone(change: number): string {
  if (change > 0) return 'tone-green'
  if (change < 0) return 'tone-red'
  return 'tone-neutral'
}

function DashboardPage() {
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

  async function load() {
    if (period === 'custom' && (!customFrom || !customTo)) return
    try { setData(await api<Dashboard>(`/api/dashboard?${params()}`)); setError('') }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load dashboard.') }
  }
  useEffect(() => { void load() }, [period, customFrom, customTo, ruleFilter, networkFilter])

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

export default function Workspace({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const [view, setView] = useState<'rules' | 'users' | 'account' | 'messages' | 'dashboard' | 'settings' | 'blocklist'>('rules')
  const [currentUser, setCurrentUser] = useState(user)
  const canEdit = currentUser.role === 'super_admin' || currentUser.role === 'operator'
  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <a className="wordmark" href="/" aria-label="Upenflow Notify"><span className="brand-mark"><span /></span><span>upenflow<span className="wordmark-light"> notify</span></span></a>
        <nav className="workspace-nav" aria-label="Primary navigation">
          <button className={view === 'dashboard' ? 'nav-item selected' : 'nav-item'} type="button" onClick={() => setView('dashboard')}>Dashboard</button>
          <button className={view === 'messages' ? 'nav-item selected' : 'nav-item'} type="button" onClick={() => setView('messages')}>Notifications</button>
          <button className={view === 'rules' ? 'nav-item selected' : 'nav-item'} type="button" onClick={() => setView('rules')}>Rules</button>
          {(currentUser.role === 'super_admin' || currentUser.role === 'operator') && <button className={view === 'blocklist' ? 'nav-item selected' : 'nav-item'} type="button" onClick={() => setView('blocklist')}>Blocklist</button>}
          {currentUser.role === 'super_admin' && <><button className={view === 'users' ? 'nav-item selected' : 'nav-item'} type="button" onClick={() => setView('users')}>Users</button><button className={view === 'settings' ? 'nav-item selected' : 'nav-item'} type="button" onClick={() => setView('settings')}>Settings</button></>}
          <button className={view === 'account' ? 'nav-item selected' : 'nav-item'} type="button" onClick={() => setView('account')}>My account</button>
        </nav>
        <div className="workspace-user"><span className="user-initial">{currentUser.name.slice(0, 1).toUpperCase()}</span><span className="user-meta"><strong>{currentUser.name}</strong><small>{currentUser.role.replace('_', ' ')}</small></span><button className="quiet-icon" type="button" title="Sign out" onClick={onSignOut}><LogOut size={17} /></button></div>
      </header>
      <SendingBanner isAdmin={currentUser.role === 'super_admin'} />
      {view === 'rules' && <RulesPage canEdit={canEdit} />}
      {view === 'messages' && <NotificationsPage canExport={currentUser.role === 'super_admin' || currentUser.role === 'operator'} />}
      {view === 'dashboard' && <DashboardPage />}
      {view === 'users' && currentUser.role === 'super_admin' && <UsersPage />}
      {view === 'settings' && currentUser.role === 'super_admin' && <SettingsPage />}
      {view === 'blocklist' && (currentUser.role === 'super_admin' || currentUser.role === 'operator') && <BlocklistPage />}
      {view === 'account' && <AccountPage user={currentUser} onUserUpdated={setCurrentUser} />}
      <footer className="workspace-footer"><span>UPENFLOW NOTIFY</span><span>RULES ARE VERSIONED WHEN CHANGED</span></footer>
    </main>
  )
}
type BlockedNumber = { id: number; phone_number: string; reason: string | null; created_at: string }