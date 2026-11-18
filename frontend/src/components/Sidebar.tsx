import type { ReactNode } from 'react'
import {
  Archive, BellRing, ChevronDown, CreditCard, Gauge, Laptop2, LayoutDashboard, Moon, MessageSquare,
  Route, Server, ShieldAlert, ShieldBan, ShieldCheck, Signal, SlidersHorizontal, UserCircle, Users,
} from 'lucide-react'
import type { AccountSection, SettingsSection, View } from '../types'

const ACCOUNT_NAV_ITEMS: { id: AccountSection; label: string; icon: ReactNode }[] = [
  { id: 'profile', label: 'Profile', icon: <UserCircle size={17} /> },
  { id: 'security', label: 'Security', icon: <ShieldCheck size={17} /> },
  { id: 'sessions', label: 'Sessions', icon: <Laptop2 size={17} /> },
]

const SETTINGS_NAV_ITEMS: { id: SettingsSection; label: string; icon: ReactNode }[] = [
  { id: 'billing', label: 'Billing', icon: <CreditCard size={17} /> },
  { id: 'gateway', label: 'Gateway', icon: <Server size={17} /> },
  { id: 'limits', label: 'Delivery limits', icon: <Gauge size={17} /> },
  { id: 'safety', label: 'Safeguards', icon: <ShieldAlert size={17} /> },
  { id: 'quiet-hours', label: 'Quiet hours', icon: <Moon size={17} /> },
  { id: 'retention', label: 'Data retention', icon: <Archive size={17} /> },
  { id: 'monitoring', label: 'Monitoring & alerts', icon: <BellRing size={17} /> },
  { id: 'network', label: 'Network prefixes', icon: <Signal size={17} /> },
]

function NavButton({ active, icon, label, onClick }: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <li>
      <button className={active ? 'side-nav-item selected' : 'side-nav-item'} type="button" aria-current={active ? 'page' : undefined} onClick={onClick}>
        {icon}<span className="side-nav-label">{label}</span>
      </button>
    </li>
  )
}

export function Sidebar({
  view, setView, settingsSection, setSettingsSection, collapsed, settingsOpen, setSettingsOpen,
  accountSection, setAccountSection, accountOpen, setAccountOpen, role, mobileOpen, onNavigate,
}: {
  view: View; setView: (view: View) => void; settingsSection: SettingsSection; setSettingsSection: (section: SettingsSection) => void
  collapsed: boolean; settingsOpen: boolean; setSettingsOpen: (updater: (value: boolean) => boolean) => void
  accountSection: AccountSection; setAccountSection: (section: AccountSection) => void
  accountOpen: boolean; setAccountOpen: (updater: (value: boolean) => boolean) => void
  role: string; mobileOpen: boolean; onNavigate: () => void
}) {
  const isSuperAdmin = role === 'super_admin'
  const canManage = role === 'super_admin' || role === 'operator'

  function go(next: View) { setView(next); onNavigate() }
  function goSettings(section: SettingsSection) { setView('settings'); setSettingsSection(section); onNavigate() }
  function toggleSettingsGroup() { setSettingsOpen((value) => !value) }
  function goAccount(section: AccountSection) { setView('account'); setAccountSection(section); onNavigate() }
  function toggleAccountGroup() { setAccountOpen((value) => !value) }

  return (
    <nav className={`side-nav${collapsed ? ' collapsed' : ''}${mobileOpen ? ' mobile-open' : ''}`} aria-label="Primary">
      <ul className="side-nav-list">
        <NavButton active={view === 'dashboard'} icon={<LayoutDashboard size={18} />} label="Dashboard" onClick={() => go('dashboard')} />
        <NavButton active={view === 'messages'} icon={<MessageSquare size={18} />} label="Notifications" onClick={() => go('messages')} />
        <NavButton active={view === 'rules'} icon={<Route size={18} />} label="Rules" onClick={() => go('rules')} />
        {canManage && <NavButton active={view === 'blocklist'} icon={<ShieldBan size={18} />} label="Blocklist" onClick={() => go('blocklist')} />}
        {isSuperAdmin && (
          <li className="side-nav-group">
            <button
              className="side-nav-item side-nav-group-toggle"
              type="button"
              aria-expanded={settingsOpen}
              aria-controls="settings-subnav"
              onClick={toggleSettingsGroup}
            >
              <SlidersHorizontal size={18} /><span className="side-nav-label">Settings</span>
              <ChevronDown size={14} className={settingsOpen ? 'side-nav-chevron open' : 'side-nav-chevron'} />
            </button>
            <ul id="settings-subnav" className="side-nav-sublist" hidden={!settingsOpen || collapsed}>
              {SETTINGS_NAV_ITEMS.map((item) => (
                <li key={item.id}>
                  <button
                    className={view === 'settings' && settingsSection === item.id ? 'side-nav-subitem selected' : 'side-nav-subitem'}
                    type="button"
                    aria-current={view === 'settings' && settingsSection === item.id ? 'page' : undefined}
                    onClick={() => goSettings(item.id)}
                  >
                    {item.icon}<span className="side-nav-label">{item.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </li>
        )}
        {isSuperAdmin && <NavButton active={view === 'users'} icon={<Users size={18} />} label="Users" onClick={() => go('users')} />}
        <li className="side-nav-group">
          <button
            className="side-nav-item side-nav-group-toggle"
            type="button"
            aria-expanded={accountOpen}
            aria-controls="account-subnav"
            onClick={toggleAccountGroup}
          >
            <UserCircle size={18} /><span className="side-nav-label">My account</span>
            <ChevronDown size={14} className={accountOpen ? 'side-nav-chevron open' : 'side-nav-chevron'} />
          </button>
          <ul id="account-subnav" className="side-nav-sublist" hidden={!accountOpen || collapsed}>
            {ACCOUNT_NAV_ITEMS.map((item) => (
              <li key={item.id}>
                <button
                  className={view === 'account' && accountSection === item.id ? 'side-nav-subitem selected' : 'side-nav-subitem'}
                  type="button"
                  aria-current={view === 'account' && accountSection === item.id ? 'page' : undefined}
                  onClick={() => goAccount(item.id)}
                >
                  {item.icon}<span className="side-nav-label">{item.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </li>
      </ul>
    </nav>
  )
}
