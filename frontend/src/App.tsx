import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowLeft, ArrowRight, LockKeyhole, Mail, ShieldCheck } from 'lucide-react'
import Workspace from './Workspace'

type User = { name: string; email: string; role: string }
type ApiError = { detail?: string }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiError
    throw new Error(body.detail ?? 'Something went wrong. Please try again.')
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [step, setStep] = useState<'login' | 'otp'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [resendIn, setResendIn] = useState(60)
  const [expiresIn, setExpiresIn] = useState(300)
  const [resetToken] = useState(() => new URLSearchParams(window.location.search).get('token'))
  const otpInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    request<User>('/api/auth/me').then(setUser).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (step !== 'otp') return
    const timer = window.setInterval(() => {
      setResendIn((value) => Math.max(0, value - 1))
      setExpiresIn((value) => Math.max(0, value - 1))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [step])

  useEffect(() => {
    if (step === 'otp') otpInput.current?.focus()
  }, [step])

  async function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setMessage('')
    try {
      await request('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      setStep('otp')
      setCode('')
      setResendIn(60)
      setExpiresIn(300)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to sign in.')
    } finally {
      setBusy(false)
    }
  }

  async function submitCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (code.length !== 6) return
    setBusy(true)
    setMessage('')
    try {
      const result = await request<{ user: User }>('/api/auth/verify-otp', {
        method: 'POST',
        body: JSON.stringify({ code }),
      })
      setUser(result.user)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'That code could not be verified.')
      setCode('')
      otpInput.current?.focus()
    } finally {
      setBusy(false)
    }
  }

  async function resendCode() {
    setBusy(true)
    setMessage('')
    try {
      await request('/api/auth/resend-otp', { method: 'POST' })
      setResendIn(60)
      setExpiresIn(300)
      setCode('')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to resend the code.')
    } finally {
      setBusy(false)
    }
  }

  async function requestPasswordReset() {
    setMessage('')
    if (!email) {
      setMessage('Enter your work email first.')
      return
    }
    setBusy(true)
    try {
      const result = await request<{ message: string }>('/api/auth/forgot-password', {
        method: 'POST',
        body: JSON.stringify({ email }),
      })
      setMessage(result.message)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to request a password reset.')
    } finally {
      setBusy(false)
    }
  }

  async function signOut() {
    await request('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
    setUser(null)
    setStep('login')
    setPassword('')
    setCode('')
  }

  if (resetToken) return <SetPasswordPage token={resetToken} />

  if (user) {
    return <Workspace user={user} onSignOut={signOut} />
  }

  return (
    <main className="auth-shell">
      <aside className="brand-panel">
        <div className="brand-panel-grain" />
        <a className="wordmark wordmark-inverse" href="/" aria-label="Upenflow Notify">
          <span className="brand-mark"><span /></span>
          <span>upenflow<span className="wordmark-light"> notify</span></span>
        </a>
        <div className="brand-art" aria-hidden="true">
          <div className="art-orbit orbit-one" />
          <div className="art-orbit orbit-two" />
          <div className="art-orbit orbit-three" />
          <div className="art-core"><span className="core-pulse" /><span className="core-stem" /></div>
          <div className="art-node node-a"><i /><span>UPSTREAM</span><b>SERVICE A</b></div>
          <div className="art-node node-b"><i /><span>ROUTING</span><b>RULE ENGINE</b></div>
          <div className="art-node node-c"><i /><span>DELIVERY</span><b>SERVICE B</b></div>
          <div className="art-line line-a" /><div className="art-line line-b" />
        </div>
        <div className="brand-caption"><span>01 / 03</span><span className="caption-rule" /><span>OPERATIONS CONSOLE</span></div>
        <div className="brand-foot"><span>NAIROBI, KE</span><span>EST. 2026</span></div>
      </aside>

      <section className="form-panel">
        <div className="form-topline"><span>SECURE ACCESS</span><span><span className="topline-indicator" /> ENCRYPTED</span></div>
        <div className="form-content" key={step}>
          {step === 'login' ? (
            <>
              <div className="form-kicker"><span>WELCOME</span><span className="kicker-line" /></div>
              <h1>Sign in to<br /><em>your workspace.</em></h1>
              <p className="form-description">Use your team account to continue.</p>
              <form className="auth-form" onSubmit={submitLogin}>
                <label htmlFor="email">Work email</label>
                <div className="input-wrap">
                  <Mail size={18} aria-hidden="true" />
                  <input id="email" type="email" autoComplete="username" placeholder="name@company.com" value={email} onChange={(event) => setEmail(event.target.value)} required />
                </div>
                <div className="password-label"><label htmlFor="password">Password</label><button className="text-button" type="button" disabled={busy} onClick={() => void requestPasswordReset()}>Forgot password?</button></div>
                <div className="input-wrap">
                  <LockKeyhole size={18} aria-hidden="true" />
                  <input id="password" type="password" autoComplete="current-password" placeholder="Enter your password" value={password} onChange={(event) => setPassword(event.target.value)} required />
                </div>
                {message && <p className="form-message" role="alert">{message}</p>}
                <button className="submit-button" type="submit" disabled={busy}>
                  <span>{busy ? 'Checking credentials' : 'Continue securely'}</span><ArrowRight size={18} />
                </button>
              </form>
              <div className="form-security"><ShieldCheck size={16} /><span>Your session is protected with two-step verification.</span></div>
            </>
          ) : (
            <>
              <button className="back-button" type="button" onClick={() => { setStep('login'); setMessage('') }}><ArrowLeft size={17} /> Use a different account</button>
              <div className="form-kicker"><span>CHECK YOUR INBOX</span><span className="kicker-line" /></div>
              <h1>One last<br /><em>security check.</em></h1>
              <p className="form-description">Enter the 6-digit code sent to <strong>{email}</strong>.</p>
              <form className="auth-form otp-form" onSubmit={submitCode}>
                <label htmlFor="otp-code">Verification code</label>
                <div className="otp-boxes" onClick={() => otpInput.current?.focus()}>
                  {Array.from({ length: 6 }, (_, index) => <span className={index === code.length ? 'otp-box active' : 'otp-box'} key={index}>{code[index] ?? ''}</span>)}
                  <input ref={otpInput} id="otp-code" className="otp-input" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} aria-label="6-digit verification code" />
                </div>
                <div className="otp-timers"><span>CODE EXPIRES IN <strong>{Math.floor(expiresIn / 60)}:{String(expiresIn % 60).padStart(2, '0')}</strong></span><button className="text-button" type="button" disabled={busy || resendIn > 0} onClick={resendCode}>{resendIn > 0 ? `Resend in ${resendIn}s` : 'Resend code'}</button></div>
                {message && <p className="form-message" role="alert">{message}</p>}
                <button className="submit-button" type="submit" disabled={busy || code.length !== 6}>
                  <span>{busy ? 'Verifying code' : 'Verify and sign in'}</span><ArrowRight size={18} />
                </button>
              </form>
              <div className="form-security"><ShieldCheck size={16} /><span>Never share this code with anyone.</span></div>
            </>
          )}
        </div>
        <footer className="form-footer"><span>© 2026 UPENFLOW</span><span>HELP &amp; SUPPORT</span></footer>
      </section>
    </main>
  )
}

function SetPasswordPage({ token }: { token: string }) {
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [complete, setComplete] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await request('/api/auth/set-password', {
        method: 'POST',
        body: JSON.stringify({ token, new_password: password, confirm_password: confirmPassword }),
      })
      setComplete(true)
      window.history.replaceState({}, '', '/')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'This link is invalid or has expired.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-shell">
      <aside className="brand-panel"><a className="wordmark wordmark-inverse" href="/"><span className="brand-mark"><span /></span><span>upenflow<span className="wordmark-light"> notify</span></span></a><div className="brand-foot"><span>NAIROBI, KE</span><span>SECURE ACCESS</span></div></aside>
      <section className="form-panel">
        <div className="form-topline"><span>ACCOUNT SECURITY</span><span>ONE-TIME LINK</span></div>
        <div className="form-content">
          {complete ? <><div className="form-kicker"><span>ALL SET</span><span className="kicker-line" /></div><h1>Password<br /><em>updated.</em></h1><p className="form-description">Your password is ready. Sign in with your new credentials.</p><a className="submit-button setup-link" href="/"><span>Return to sign in</span><ArrowRight size={18} /></a></> : <><div className="form-kicker"><span>SET PASSWORD</span><span className="kicker-line" /></div><h1>Make it<br /><em>yours.</em></h1><p className="form-description">Choose a strong password with at least 12 characters, letters, and numbers.</p><form className="auth-form" onSubmit={submit}><label htmlFor="new-password">New password</label><div className="input-wrap"><LockKeyhole size={18} /><input id="new-password" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={12} required /></div><label htmlFor="confirm-password">Confirm password</label><div className="input-wrap"><LockKeyhole size={18} /><input id="confirm-password" type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} minLength={12} required /></div>{error && <p className="form-message" role="alert">{error}</p>}<button className="submit-button" type="submit" disabled={busy}><span>{busy ? 'Saving password' : 'Set password'}</span><ArrowRight size={18} /></button></form></>}
        </div>
        <footer className="form-footer"><span>© 2026 UPENFLOW</span><span>SECURE ACCESS</span></footer>
      </section>
    </main>
  )
}

export default App