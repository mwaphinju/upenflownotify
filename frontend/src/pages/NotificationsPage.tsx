import { useEffect, useState } from 'react'
import { ArrowUpRight, ChevronDown, ChevronLeft, ChevronRight, CirclePlus, Clock, Download, RefreshCw, Search, X } from 'lucide-react'
import { api } from '../api'
import { useAutoRefresh } from '../hooks'
import { SendMessageDialog } from '../components/SendMessageDialog'
import type { Message, MessageDetail } from '../types'

function normalizeDisplayPhone(value: string): boolean {
  const digits = value.replace(/[\s()+-]/g, '')
  return /^(0\d{9}|\d{9}|254\d{9})$/.test(digits)
}

export function NotificationsPage({ canExport }: { canExport: boolean }) {
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
  const [showSendDialog, setShowSendDialog] = useState(false)

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

  async function loadMessages(silent = false) {
    if (!silent) setLoading(true)
    const params = filterParams()
    const url = new URL(window.location.href)
    url.search = params.toString()
    window.history.replaceState({}, '', url)
    try {
      const result = await api<{ items: Message[]; total: number; pages: number }>(`/api/messages?${params}`)
      setItems(result.items); setTotal(result.total); setPages(result.pages); if (!silent) setError('')
    } catch (reason) { if (!silent) setError(reason instanceof Error ? reason.message : 'Unable to load notifications.') }
    finally { if (!silent) setLoading(false) }
  }
  useEffect(() => { void loadMessages() }, [page, status, network])
  useAutoRefresh(() => { void loadMessages(true) }, 15000)

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
      <div className="page-heading"><div><div className="section-kicker">MESSAGE ACTIVITY / 07</div><h1>Notifications</h1><p>Search fulfilment messages and inspect their routing result.</p></div><div className="page-heading-actions">{canExport && <button className="primary-button" type="button" onClick={() => setShowSendDialog(true)}><CirclePlus size={16} /> Send message</button>}{canExport && <a className="secondary-button export-button" href={`/api/messages/export.csv?${filterParams()}`}><Download size={15} /> Export CSV</a>}</div></div>
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
      {showSendDialog && <SendMessageDialog onClose={() => setShowSendDialog(false)} onSent={async () => { setNotice('Message sent.'); await loadMessages() }} />}
    </div>
  )
}
