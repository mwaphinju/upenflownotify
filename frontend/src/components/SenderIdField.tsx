import { ChevronDown } from 'lucide-react'
import { useSenderIds } from '../hooks'

export function SenderIdField({ value, onChange, required, blankLabel }: { value: string; onChange: (value: string) => void; required?: boolean; blankLabel?: string }) {
  const senderIds = useSenderIds()
  if (senderIds && senderIds.allowed_sender_ids.length > 0) {
    return (
      <span className="select-wrap">
        <select value={value} onChange={(event) => onChange(event.target.value)} required={required}>
          {!value && <option value="">{blankLabel ?? 'Select a Sender ID…'}</option>}
          {senderIds.allowed_sender_ids.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
        <ChevronDown size={15} />
      </span>
    )
  }
  return <input value={value} onChange={(event) => onChange(event.target.value.toUpperCase())} required={required} maxLength={11} placeholder="No Sender IDs configured yet" />
}
