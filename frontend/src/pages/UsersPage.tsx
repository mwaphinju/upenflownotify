import { useEffect, useState, type FormEvent } from 'react'
import { ArrowDown, CirclePlus, KeyRound, LogOut, X } from 'lucide-react'
import { api } from '../api'
import { useAutoRefresh } from '../hooks'
import type { ManagedUser } from '../types'

export function UsersPage() {
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState({ name: '', email: '', role: 'operator' })
  const [showCreate, setShowCreate] = useState(false)
  const [saving, setSaving] = useState(false)

  async function loadUsers(silent = false) {
    if (!silent) setLoading(true)
    try { setUsers(await api<ManagedUser[]>('/api/admin/users')); if (!silent) setError('') }
    catch (reason) { if (!silent) setError(reason instanceof Error ? reason.message : 'Unable to load users.') }
    finally { if (!silent) setLoading(false) }
  }
  useEffect(() => { void loadUsers() }, [])
  useAutoRefresh(() => { void loadUsers(true) }, 30000)

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
