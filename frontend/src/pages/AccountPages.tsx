import { useEffect, useState, type FormEvent } from 'react'
import { ArrowDown, Check, UserRound, X } from 'lucide-react'
import { api } from '../api'
import { useAutoRefresh } from '../hooks'
import type { AccountSection, ActiveSession, User } from '../types'
import { SettingsPageShell } from './SettingsPages'

function ProfileSettingsPage({ user, onUserUpdated }: { user: User; onUserUpdated: (user: User) => void }) {
  const [name, setName] = useState(user.name)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setSaving(true)
    try {
      const updated = await api<User>('/api/me', { method: 'PATCH', body: JSON.stringify({ name }) })
      onUserUpdated(updated); setNotice('Profile updated.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to update profile.') }
    finally { setSaving(false) }
  }

  return (
    <SettingsPageShell kicker="MY ACCOUNT / PROFILE" title="Profile" description="Your display name and account role." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      <form className="settings-form-page" onSubmit={saveProfile}>
        <section className="md-card">
          <div className="settings-grid">
            <label>Display name<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
            <label>Email address<input value={user.email} disabled /></label>
          </div>
        </section>
        <div className="settings-save-row"><span className="account-state active"><i />{user.role.replace('_', ' ')}</span><button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save changes'} <Check size={15} /></button></div>
      </form>
    </SettingsPageShell>
  )
}

function SecuritySettingsPage() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [challengeToken, setChallengeToken] = useState('')
  const [code, setCode] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

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
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The code could not be verified.') }
  }

  return (
    <SettingsPageShell kicker="MY ACCOUNT / SECURITY" title="Change password" description="Confirmed by a code sent to your email." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      <section className="md-card">
        {challengeToken ? (
          <form className="settings-form" onSubmit={confirmPasswordChange}>
            <p className="inline-instruction">Enter the code sent to your email to confirm this change.</p>
            <label>6-digit code<input value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" required /></label>
            <button className="primary-button" type="submit" disabled={code.length !== 6}>Confirm password change <Check size={15} /></button>
          </form>
        ) : (
          <form className="settings-form" onSubmit={startPasswordChange}>
            <label>Current password<input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label>
            <label>New password<input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required minLength={12} /></label>
            <label>Confirm new password<input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required minLength={12} /></label>
            <button className="secondary-button" type="submit">Send confirmation code <ArrowDown size={15} /></button>
          </form>
        )}
      </section>
    </SettingsPageShell>
  )
}

function SessionsSettingsPage() {
  const [sessions, setSessions] = useState<ActiveSession[] | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  async function loadSessions(silent = false) {
    try { setSessions(await api<ActiveSession[]>('/api/me/sessions')) }
    catch (reason) { if (!silent) setError(reason instanceof Error ? reason.message : 'Unable to load sessions.') }
  }
  useEffect(() => { void loadSessions() }, [])
  useAutoRefresh(() => { void loadSessions(true) }, 20000)

  async function revokeSession(session: ActiveSession) {
    try {
      await api(`/api/me/sessions/${session.id}`, { method: 'DELETE' })
      if (session.current) { window.location.reload(); return }
      setNotice('Session revoked.')
      await loadSessions()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to revoke this session.') }
  }

  return (
    <SettingsPageShell kicker="MY ACCOUNT / SESSIONS" title="Signed-in sessions" description="Devices and browsers currently signed into your account." notice={notice} error={error} onDismiss={() => { setError(''); setNotice('') }}>
      {sessions === null ? <div className="dashboard-loading">Loading sessions…</div> : (
        <div className="session-list">
          {sessions.map((session) => <div className="session-item" key={session.id}><span className="session-device"><UserRound size={17} /></span><span className="session-details"><strong>{session.device}</strong><small>{session.ip_address ?? 'IP unavailable'} · {new Date(session.last_seen_at).toLocaleString()}</small></span>{session.current && <span className="current-session">THIS DEVICE</span>}<button className="quiet-icon danger-icon" type="button" title="Revoke session" onClick={() => void revokeSession(session)}><X size={16} /></button></div>)}
          {sessions.length === 0 && <p className="empty-sessions">No active sessions.</p>}
        </div>
      )}
    </SettingsPageShell>
  )
}

export function AccountRouter({ section, user, onUserUpdated }: { section: AccountSection; user: User; onUserUpdated: (user: User) => void }) {
  switch (section) {
    case 'profile': return <ProfileSettingsPage user={user} onUserUpdated={onUserUpdated} />
    case 'security': return <SecuritySettingsPage />
    case 'sessions': return <SessionsSettingsPage />
  }
}
