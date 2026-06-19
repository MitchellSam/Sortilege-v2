import { useState, useEffect, useCallback } from 'react'
import { api, sseConnect } from '../api'
import FolderTree from '../components/FolderTree'
import ReviewQueue from '../components/ReviewQueue'

export default function ReviewScreen() {
  const [data, setData]         = useState(null)
  const [taxonomy, setTaxonomy] = useState([])
  const [batches, setBatches]   = useState([])
  const [loading, setLoading]   = useState(true)
  const [toast, setToast]       = useState(null)

  const refresh = useCallback(() => {
    Promise.all([api.getFiles(), api.getTaxonomy(), api.getBatches(5)])
      .then(([f, t, b]) => {
        setData(f)
        setTaxonomy(t.nodes ?? [])
        setBatches(b.batches ?? [])
        setLoading(false)
      })
      .catch(err => { console.error(err); setLoading(false) })
  }, [])

  useEffect(() => {
    refresh()
    return sseConnect((type, payload) => {
      if (type === 'batch_ready') {
        refresh()
        showToast(`${payload.held + payload.skipped} files ready for review`)
      }
      if (type === 'budget_paused') {
        showToast(`Budget paused — $${payload.spent_usd.toFixed(2)} / $${payload.ceiling_usd}`, 'amber')
      }
    })
  }, [refresh])

  function showToast(msg, color) {
    setToast({ msg, color: color ?? 'green' })
    setTimeout(() => setToast(null), 4000)
  }

  if (loading) return <div style={{ padding: 32, color: 'var(--text-secondary)' }}>Loading…</div>

  return (
    <div style={{ display: 'flex', height: '100%', position: 'relative' }}>
      <FolderTree nodes={taxonomy} />
      <ReviewQueue
        data={data}
        taxonomy={taxonomy}
        batches={batches}
        onConfirm={async (fileIds, overrides) => {
          const res = await api.confirm(fileIds, overrides)
          refresh()
          showToast(`Batch confirmed — ${res.moved + res.copied + res.skipped} files`)
          return res
        }}
        onUndo={async (batchId) => {
          await api.undo(batchId)
          refresh()
          showToast('Batch undone')
        }}
        onAcceptSuggestion={async (id) => { await api.acceptSuggestion(id); refresh() }}
        onDismissSuggestion={async (id) => { await api.dismissSuggestion(id); refresh() }}
      />
      {toast && <Toast msg={toast.msg} color={toast.color} />}
    </div>
  )
}

function Toast({ msg, color }) {
  const colors = { green: 'var(--green)', amber: 'var(--amber)', red: 'var(--red)' }
  return (
    <div style={{
      position: 'absolute',
      bottom: 24,
      left: '50%',
      transform: 'translateX(-50%)',
      background: 'var(--bg-card)',
      border: `1px solid ${colors[color] ?? colors.green}`,
      color: colors[color] ?? colors.green,
      padding: '8px 18px',
      borderRadius: 'var(--radius)',
      boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
      fontWeight: 500,
      zIndex: 100,
      whiteSpace: 'nowrap',
    }}>
      {msg}
    </div>
  )
}
