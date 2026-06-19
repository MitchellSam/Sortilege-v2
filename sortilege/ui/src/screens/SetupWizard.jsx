import { useState } from 'react'
import { api } from '../api'

const DEFAULT_FOLDERS = [
  { name: 'financial',  description: 'Taxes, statements, insurance, receipts' },
  { name: 'career',     description: 'Resumes, certifications, job-search artifacts' },
  { name: 'health',     description: 'Medical records, lab results, imaging' },
  { name: 'documents',  description: 'Identity, legal, manuals, correspondence' },
  { name: 'photos',     description: 'Personal photos — camera, family, events' },
  { name: 'media',      description: 'Downloaded images, wallpapers, video, audio' },
  { name: 'code',       description: 'Projects, snippets, dotfiles' },
  { name: 'creative',   description: 'Writing, worldbuilding, campaign materials' },
]

export default function SetupWizard({ onDone }) {
  const [step, setStep] = useState(1)
  const [state, setState] = useState({
    output_root: 'E:\\organized',
    api_key: '',
    folders: DEFAULT_FOLDERS.map((f, i) => ({ ...f, id: i })),
  })

  function update(patch) { setState(s => ({ ...s, ...patch })) }
  function next() { setStep(s => s + 1) }

  const steps = [Step1, Step2, Step3, Step4, Step5]
  const StepComp = steps[step - 1]

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'flex-start',
      minHeight: '100%',
      padding: '48px 16px',
      background: 'var(--bg-base)',
    }}>
      <div style={{ width: '100%', maxWidth: 560 }}>
        {/* Progress */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 32, justifyContent: 'center' }}>
          {[1, 2, 3, 4, 5].map(n => (
            <div key={n} style={{
              width: 28, height: 28,
              borderRadius: '50%',
              background: n === step ? 'var(--accent)' : n < step ? 'var(--green)' : 'var(--bg-card)',
              border: `2px solid ${n === step ? 'var(--accent)' : n < step ? 'var(--green)' : 'var(--border)'}`,
              color: n <= step ? '#fff' : 'var(--text-secondary)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 12, fontWeight: 600,
            }}>
              {n < step ? '✓' : n}
            </div>
          ))}
        </div>

        <StepComp state={state} update={update} onNext={next} onDone={onDone} />
      </div>
    </div>
  )
}

function Card({ children }) {
  return (
    <div style={{
      background: 'var(--bg-panel)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      padding: 28,
    }}>
      {children}
    </div>
  )
}

function Heading({ children }) {
  return <h2 style={{ marginBottom: 20, fontSize: 18, fontWeight: 600 }}>{children}</h2>
}

// Step 1: Output destination
function Step1({ state, update, onNext }) {
  const [status, setStatus] = useState(null)
  const [checking, setChecking] = useState(false)

  async function validate() {
    setChecking(true)
    try {
      const res = await api.validatePath(state.output_root)
      setStatus(res)
    } catch (e) {
      setStatus({ ok: false, error: e.message })
    } finally {
      setChecking(false)
    }
  }

  return (
    <Card>
      <Heading>Where should your organized files live?</Heading>
      <div style={{ marginBottom: 12 }}>
        <input
          value={state.output_root}
          onChange={e => update({ output_root: e.target.value })}
          placeholder="E:\organized"
        />
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button className="btn-ghost" onClick={validate} disabled={checking} style={{ fontSize: 12 }}>
          {checking ? 'Checking…' : 'Validate'}
        </button>
      </div>
      {status && (
        <div style={{
          marginBottom: 16,
          color: status.ok ? 'var(--green)' : 'var(--red)',
          fontSize: 12,
        }}>
          {status.ok ? `✓ Ready — ${status.free_gb?.toFixed(1)} GB free` : `✗ ${status.error}`}
        </div>
      )}
      <button className="btn-primary" onClick={onNext} style={{ width: '100%' }}>
        Next →
      </button>
    </Card>
  )
}

// Step 2: API key
function Step2({ state, update, onNext }) {
  const [status, setStatus] = useState(null)
  const [checking, setChecking] = useState(false)

  async function validate() {
    if (!state.api_key) return
    setChecking(true)
    try {
      const res = await api.validateKey(state.api_key)
      setStatus(res)
    } catch (e) {
      setStatus({ ok: false, error: e.message })
    } finally {
      setChecking(false)
    }
  }

  return (
    <Card>
      <Heading>Connect to Claude</Heading>
      <div style={{ marginBottom: 8 }}>
        <input
          type="password"
          value={state.api_key}
          onChange={e => update({ api_key: e.target.value })}
          placeholder="sk-ant-…"
        />
      </div>
      <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 12 }}>
        Stored securely in Windows Credential Manager — never saved to disk
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button className="btn-ghost" onClick={validate} disabled={checking || !state.api_key} style={{ fontSize: 12 }}>
          {checking ? 'Testing…' : 'Validate'}
        </button>
      </div>
      {status && (
        <div style={{
          marginBottom: 16,
          color: status.ok ? 'var(--green)' : 'var(--red)',
          fontSize: 12,
        }}>
          {status.ok ? '✓ Connected' : `✗ ${status.error}`}
        </div>
      )}
      <button className="btn-primary" onClick={onNext} style={{ width: '100%' }} disabled={!state.api_key}>
        Next →
      </button>
    </Card>
  )
}

// Step 3: Environment check
function Step3({ onNext }) {
  const [results, setResults] = useState(null)
  const [checking, setChecking] = useState(false)

  async function check() {
    setChecking(true)
    try {
      const res = await api.checkEnv()
      setResults(res.checks ?? [])
    } catch (e) {
      setResults([{ label: 'Check failed', ok: false, detail: e.message }])
    } finally {
      setChecking(false)
    }
  }

  return (
    <Card>
      <Heading>Checking your system</Heading>
      {!results && (
        <button className="btn-ghost" onClick={check} disabled={checking} style={{ marginBottom: 16 }}>
          {checking ? 'Scanning…' : 'Run Check'}
        </button>
      )}
      {results && (
        <div style={{ marginBottom: 16 }}>
          {results.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
              <span style={{ color: r.ok ? 'var(--green)' : 'var(--amber)' }}>{r.ok ? '✓' : '⚠'}</span>
              <span style={{ flex: 1 }}>{r.label}</span>
              {r.detail && <span style={{ color: 'var(--text-secondary)' }}>{r.detail}</span>}
            </div>
          ))}
        </div>
      )}
      <button className="btn-primary" onClick={onNext} style={{ width: '100%' }}>
        Next →
      </button>
    </Card>
  )
}

// Step 4: Seed taxonomy
function Step4({ state, update, onNext }) {
  function rename(id, name) {
    update({ folders: state.folders.map(f => f.id === id ? { ...f, name } : f) })
  }
  function remove(id) {
    update({ folders: state.folders.filter(f => f.id !== id) })
  }
  function add() {
    const id = Date.now()
    update({ folders: [...state.folders, { id, name: 'new-folder', description: '' }] })
  }

  return (
    <Card>
      <Heading>Set up your top-level folders</Heading>
      <div style={{ marginBottom: 12 }}>
        {state.folders.map(f => (
          <div key={f.id} style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 0',
            borderBottom: '1px solid var(--border)',
          }}>
            <span style={{ fontSize: 14 }}>📁</span>
            <div style={{ flex: 1 }}>
              <input
                value={f.name}
                onChange={e => rename(f.id, e.target.value)}
                style={{ fontSize: 13, padding: '3px 6px' }}
              />
              {f.description && (
                <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginTop: 2 }}>{f.description}</div>
              )}
            </div>
            <button onClick={() => remove(f.id)} style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              fontSize: 16,
              padding: '0 4px',
            }}>×</button>
          </div>
        ))}
        {/* Unsorted — locked */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', opacity: 0.5 }}>
          <span style={{ fontSize: 14 }}>📁</span>
          <div style={{ flex: 1 }}>
            <span style={{ fontStyle: 'italic', fontSize: 13 }}>unsorted</span>
            <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>Fallback for unclassifiable files — can't be removed</div>
          </div>
          <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>🔒</span>
        </div>
      </div>
      <button className="btn-ghost" onClick={add} style={{ fontSize: 12, marginBottom: 16 }}>
        + Add folder
      </button>
      <button className="btn-primary" onClick={onNext} style={{ width: '100%' }}>
        Next →
      </button>
    </Card>
  )
}

// Step 5: Finish
function Step5({ state, onDone }) {
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  async function finish() {
    setLoading(true)
    setError(null)
    try {
      await api.setupFinish({
        output_root: state.output_root,
        api_key:     state.api_key,
        folders:     state.folders.map(f => f.name),
      })
      onDone()
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <Heading>You're all set</Heading>
      <div style={{ marginBottom: 20, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
        <div>Output: <span className="mono" style={{ color: 'var(--text-primary)' }}>{state.output_root}</span></div>
        <div>Folders: {state.folders.map(f => f.name).join(', ')}</div>
      </div>
      {error && <div style={{ color: 'var(--red)', marginBottom: 12, fontSize: 12 }}>{error}</div>}
      <button className="btn-primary" onClick={finish} disabled={loading} style={{ width: '100%' }}>
        {loading ? 'Setting up…' : 'Create folders & start Sortilege'}
      </button>
    </Card>
  )
}
