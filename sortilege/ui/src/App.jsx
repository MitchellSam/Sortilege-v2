import { useState, useEffect } from 'react'
import ReviewScreen from './screens/ReviewScreen'
import SetupWizard from './screens/SetupWizard'
import Settings from './screens/Settings'
import { api } from './api'

function getRoute() {
  return window.location.hash.replace('#', '') || '/review'
}

export default function App() {
  const [route, setRoute] = useState(getRoute)
  const [configured, setConfigured] = useState(null)

  useEffect(() => {
    const onHash = () => setRoute(getRoute())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    api.getConfig()
      .then(cfg => {
        setConfigured(!!cfg.configured)
        if (!cfg.configured) setRoute('/setup')
      })
      .catch(() => { setConfigured(false); setRoute('/setup') })
  }, [])

  function navigate(path) {
    window.location.hash = path
  }

  if (configured === null) {
    return <div style={{ padding: 32, color: 'var(--text-secondary)' }}>Loading…</div>
  }

  if (!configured || route === '/setup') {
    return <SetupWizard onDone={() => { setConfigured(true); navigate('/review') }} />
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <NavBar route={route} navigate={navigate} />
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {route === '/review'   && <ReviewScreen />}
        {route === '/settings' && <Settings />}
      </div>
    </div>
  )
}

function NavBar({ route, navigate }) {
  return (
    <nav style={{
      height: 40,
      background: 'var(--bg-panel)',
      borderBottom: '1px solid var(--border)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 16px',
      gap: 4,
      flexShrink: 0,
    }}>
      <span style={{ color: 'var(--accent)', fontWeight: 700, marginRight: 16, fontSize: 14 }}>
        Sortilege
      </span>
      <NavItem label="Review" path="/review" active={route === '/review'} onClick={navigate} />
      <div style={{ flex: 1 }} />
      <NavItem label="⚙ Settings" path="/settings" active={route === '/settings'} onClick={navigate} />
    </nav>
  )
}

function NavItem({ label, path, active, onClick }) {
  return (
    <button
      style={{
        background: active ? 'var(--bg-hover)' : 'transparent',
        border: 'none',
        color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
        padding: '4px 10px',
        borderRadius: 'var(--radius)',
      }}
      onClick={() => onClick(path)}
    >
      {label}
    </button>
  )
}
