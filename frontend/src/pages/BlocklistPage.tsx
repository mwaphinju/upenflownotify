import { useEffect, useState, type FormEvent } from 'react'
import { Ban, X } from 'lucide-react'
import { api } from '../api'
import { useAutoRefresh } from '../hooks'
import type { BlockedNumber } from '../types'

export function BlocklistPage() {
  const [entries, setEntries] = useState<BlockedNumber[]>([])
  const [phone, setPhone] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function loadEntries(silent = false) {
    try { setEntries(await api<BlockedNumber[]>('/api/blocklist')) }
    catch (issue) { if (!silent) setError(issue instanceof Error ? issue.message : 'Unable to load the blocklist.') }
  }
  useEffect(() => { void loadEntries() }, [])
  useAutoRefresh(() => { void loadEntries(true) }, 30000)

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
