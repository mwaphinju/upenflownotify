import { useState, type FormEvent } from 'react'
import { Check, X } from 'lucide-react'
import { api } from '../api'
import { SenderIdField } from './SenderIdField'

export function SendMessageDialog({ onClose, onSent }: { onClose: () => void; onSent: () => Promise<void> }) {
  const [recipient, setRecipient] = useState('')
  const [senderId, setSenderId] = useState('')
  const [text, setText] = useState('')
  const [orderRef, setOrderRef] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSending(true); setError('')
    try {
      await api('/api/messages/manual-send', {
        method: 'POST',
        body: JSON.stringify({ recipient, text, order_ref: orderRef || null, ...(senderId ? { sender_id: senderId.toUpperCase() } : {}) }),
      })
      await onSent()
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to send this message.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="rule-dialog" role="dialog" aria-modal="true" aria-labelledby="send-dialog-title">
        <div className="dialog-heading"><div><span className="section-kicker">DIRECT SEND</span><h2 id="send-dialog-title">Send a message</h2></div><button className="quiet-icon" type="button" onClick={onClose} aria-label="Close"><X size={18} /></button></div>
        <p className="inline-instruction">Sends straight to the gateway — no mapping rule needed. Useful for testing or while Service A isn't connected yet. Still subject to throttling, duplicate protection, the blocklist, quiet hours, and the global send switch.</p>
        <form className="rule-form" onSubmit={submit}>
          <label>Recipient<input value={recipient} onChange={(event) => setRecipient(event.target.value)} required placeholder="0712345678" /></label>
          <label>Message text<textarea value={text} onChange={(event) => setText(event.target.value)} required maxLength={1600} rows={3} placeholder="Your order is on its way." /><small>{text.length} characters</small></label>
          <div className="form-grid-two">
            <label>Sender ID<SenderIdField value={senderId} onChange={setSenderId} blankLabel="Use the gateway's default Sender ID" /></label>
            <label>Order reference (optional)<input value={orderRef} onChange={(event) => setOrderRef(event.target.value)} placeholder="ORD-4012" /></label>
          </div>
          {error && <p className="workspace-error" role="alert">{error}</p>}
          <div className="dialog-actions"><button className="secondary-button" type="button" onClick={onClose}>Cancel</button><button className="primary-button" type="submit" disabled={sending || !recipient.trim() || !text.trim()}>{sending ? 'Sending…' : 'Send'} <Check size={15} /></button></div>
        </form>
      </section>
    </div>
  )
}
