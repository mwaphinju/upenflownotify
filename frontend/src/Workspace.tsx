import { useState } from 'react'
import { LogOut, Menu, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import type { AccountSection, SettingsSection, User, View } from './types'
import { SendingBanner } from './components/SendingBanner'
import { Sidebar } from './components/Sidebar'
import { RulesPage } from './pages/RulesPage'
import { NotificationsPage } from './pages/NotificationsPage'
import { DashboardPage } from './pages/DashboardPage'
import { UsersPage } from './pages/UsersPage'
import { SettingsRouter } from './pages/SettingsPages'
import { BlocklistPage } from './pages/BlocklistPage'
import { AccountRouter } from './pages/AccountPages'

export default function Workspace({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const [view, setView] = useState<View>('dashboard')
  const [settingsSection, setSettingsSection] = useState<SettingsSection>('billing')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [accountSection, setAccountSection] = useState<AccountSection>('profile')
  const [accountOpen, setAccountOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('upenflow-nav-collapsed') === '1' } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const [currentUser, setCurrentUser] = useState(user)
  const canEdit = currentUser.role === 'super_admin' || currentUser.role === 'operator'

  function toggleCollapsed() {
    setCollapsed((value) => {
      const next = !value
      try { localStorage.setItem('upenflow-nav-collapsed', next ? '1' : '0') } catch { /* ignore */ }
      return next
    })
  }

  return (
    <div className="app-shell">
      <header className="app-bar">
        <button className="icon-button nav-toggle mobile-only" type="button" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={20} /></button>
        <button className="icon-button nav-toggle desktop-only" type="button" aria-expanded={!collapsed} aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'} onClick={toggleCollapsed}>
          {collapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
        </button>
        <a className="wordmark" href="/" aria-label="Upenflow Notify"><span className="brand-mark"><span /></span><span>upenflow<span className="wordmark-light"> notify</span></span></a>
        <div className="app-bar-spacer" />
        <div className="workspace-user">
          <span className="user-initial">{currentUser.name.slice(0, 1).toUpperCase()}</span>
          <span className="user-meta"><strong>{currentUser.name}</strong><small>{currentUser.role.replace('_', ' ')}</small></span>
          <button className="icon-button" type="button" title="Sign out" aria-label="Sign out" onClick={onSignOut}><LogOut size={18} /></button>
        </div>
      </header>
      <SendingBanner isAdmin={currentUser.role === 'super_admin'} />
      <div className="app-body">
        {mobileOpen && <div className="nav-backdrop" role="presentation" onClick={() => setMobileOpen(false)} />}
        <Sidebar
          view={view} setView={setView} settingsSection={settingsSection} setSettingsSection={setSettingsSection}
          collapsed={collapsed} settingsOpen={settingsOpen} setSettingsOpen={setSettingsOpen}
          accountSection={accountSection} setAccountSection={setAccountSection} accountOpen={accountOpen} setAccountOpen={setAccountOpen}
          role={currentUser.role} mobileOpen={mobileOpen} onNavigate={() => setMobileOpen(false)}
        />
        <main className="main-content" id="main-content">
          {view === 'rules' && <RulesPage canEdit={canEdit} />}
          {view === 'messages' && <NotificationsPage canExport={currentUser.role === 'super_admin' || currentUser.role === 'operator'} />}
          {view === 'dashboard' && <DashboardPage />}
          {view === 'users' && currentUser.role === 'super_admin' && <UsersPage />}
          {view === 'settings' && currentUser.role === 'super_admin' && <SettingsRouter section={settingsSection} />}
          {view === 'blocklist' && (currentUser.role === 'super_admin' || currentUser.role === 'operator') && <BlocklistPage />}
          {view === 'account' && <AccountRouter section={accountSection} user={currentUser} onUserUpdated={setCurrentUser} />}
          <footer className="workspace-footer"><span>UPENFLOW NOTIFY</span><span>RULES ARE VERSIONED WHEN CHANGED</span></footer>
        </main>
      </div>
    </div>
  )
}
