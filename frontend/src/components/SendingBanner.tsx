import { useEffect, useState } from 'react'
import { Check, Pause, Play, Square, X } from 'lucide-react'
import { api } from '../api'
import type { SendingState } from '../types'

export function SendingBanner({ isAdmin }: { isAdmin: boolean }) {
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
