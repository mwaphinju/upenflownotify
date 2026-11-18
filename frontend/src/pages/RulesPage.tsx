import { useEffect, useState, type FormEvent } from 'react'
import { ArrowDown, ArrowUp, Check, ChevronDown, CirclePlus, FlaskConical, History, Pencil, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { useAutoRefresh } from '../hooks'
import { SenderIdField } from '../components/SenderIdField'
import type { Rule, RuleDraft, RuleVersion, TestResult } from '../types'

const emptyDraft: RuleDraft = {
  name: '', priority: 10, match_type: 'contains', match_value: '', case_sensitive: false,
  sender_id: 'UPENFLOW', outbound_template: '', is_enabled: true,
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
            <label>Sender ID<SenderIdField value={draft.sender_id} onChange={(value) => change('sender_id', value)} required /></label>
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

export function RulesPage({ canEdit }: { canEdit: boolean }) {
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

  async function loadRules(silent = false) {
    if (!silent) setLoading(true)
    try {
      setRules(await api<Rule[]>('/api/rules'))
      setError('')
    } catch (reason) {
      if (!silent) setError(reason instanceof Error ? reason.message : 'Unable to load rules.')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => { void loadRules() }, [])
  useAutoRefresh(() => { void loadRules(true) }, 30000)

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
