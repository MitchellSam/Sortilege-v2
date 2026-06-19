import { useState, useEffect } from 'react'
import { api } from '../api'

export default function Settings() {
  const [config, setConfig] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved,  setSaved]  = useState(false)

  useEffect(() => {
    api.getConfig().then(setConfig)
  }, [])

  async function save() {
    setSaving(true)
    try {
      await api.updateConfig(config)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  if (!config) return <div style={{ padding: 32, color: 'var(--text-secondary)' }}>Loading…</div>

  const thresholds = config.confidence_thresholds ?? {}
  const spent      = 0 // TODO: pull from /api/usage when added
  const ceiling    = config.api_cost_ceiling_usd ?? 10

  return (
    <div style={{ maxWidth: 560, margin: '32px auto', padding: '0 16px' }}>
      <h2 style={{ marginBottom: 20 }}>Settings</h2>

      <Section label="Output Destination">
        <input
          value={config.output_root ?? ''}
          onChange={e => setConfig(c => ({ ...c, output_root: e.target.value }))}
        />
      </Section>

      <Section label="API Cost Ceiling ($)">
        <input
          type="number"
          step="1"
          value={ceiling}
          onChange={e => setConfig(c => ({ ...c, api_cost_ceiling_usd: parseFloat(e.target.value) }))}
          style={{ width: 120 }}
        />
        <div style={{ marginTop: 8, color: 'var(--text-secondary)', fontSize: 12 }}>
          Current spend: ${spent.toFixed(2)} / ${ceiling.toFixed(2)}
          <div style={{ height: 4, background: 'var(--bg-hover)', borderRadius: 2, marginTop: 4 }}>
            <div style={{
              height: '100%',
              width: `${Math.min(100, (spent / ceiling) * 100)}%`,
              background: spent >= ceiling ? 'var(--red)' : 'var(--accent)',
              borderRadius: 2,
            }} />
          </div>
        </div>
      </Section>

      <Section label="Confidence Thresholds">
        <div style={{ display: 'grid', gridTemplateColumns: '180px 100px', gap: '6px 12px', alignItems: 'center' }}>
          {[
            ['Tier 2 rules min',     'tier2_rules_min'],
            ['Tier 3 embedding min', 'tier3_embedding_min'],
            ['Tier 4 Haiku min',     'tier4_haiku_min'],
            ['Tier 5 Sonnet min',    'tier5_sonnet_min'],
          ].map(([label, key]) => (
            <>
              <span key={label + '_label'} style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{label}</span>
              <input
                key={label + '_input'}
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={thresholds[key] ?? ''}
                onChange={e => setConfig(c => ({
                  ...c,
                  confidence_thresholds: {
                    ...c.confidence_thresholds,
                    [key]: e.target.value === '' ? null : parseFloat(e.target.value),
                  },
                }))}
                style={{ width: '100%' }}
              />
            </>
          ))}
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 8 }}>
          These are placeholders until calibrated via dry-run
        </div>
      </Section>

      <div style={{ marginTop: 24, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button className="btn-primary" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saved && <span style={{ color: 'var(--green)', fontSize: 12 }}>✓ Saved</span>}
      </div>
    </div>
  )
}

function Section({ label, children }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {label}
      </div>
      {children}
    </div>
  )
}
