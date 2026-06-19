import { useState } from 'react'
import GroupRow from './GroupRow'

export default function ReviewQueue({ data, batches, onConfirm, onUndo, onAcceptSuggestion, onDismissSuggestion }) {
  const [checked, setChecked]   = useState(new Set())
  const [confirming, setConf]   = useState(false)
  const [showConfirm, setShowC] = useState(false)

  const groups      = data?.groups      ?? []
  const suggestions = data?.suggestions ?? []
  const counts      = data?.counts      ?? {}

  const THRESHOLD = 0.85

  function toggleGroup(key) {
    setChecked(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function selectAllHigh() {
    const highKeys = groups
      .filter(g => (g.min_confidence ?? 0) >= THRESHOLD && g.kind !== 'error')
      .map(g => groupKey(g))
    setChecked(new Set(highKeys))
  }

  async function handleConfirmSelected() {
    const selectedGroups = groups.filter(g => checked.has(groupKey(g)))
    const fileIds = selectedGroups.flatMap(g => g.files.map(f => f.id))
    if (!fileIds.length) return
    setConf(true)
    try {
      await onConfirm(fileIds, {})
      setChecked(new Set())
    } finally {
      setConf(false)
      setShowC(false)
    }
  }

  const lastBatch = batches[0]

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Toolbar */}
      <div style={{
        height: 44,
        background: 'var(--bg-panel)',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 12px',
        gap: 8,
        flexShrink: 0,
      }}>
        <button onClick={selectAllHigh} className="btn-ghost" style={{ fontSize: 12 }}>
          Select High-Confidence
        </button>
        <button
          onClick={() => setShowC(true)}
          disabled={checked.size === 0 || confirming}
          className="btn-primary"
          style={{ fontSize: 12 }}
        >
          Confirm Selected ({checked.size})
        </button>
        <div style={{ flex: 1 }} />
        {lastBatch && (
          <button onClick={() => onUndo(lastBatch.id)} className="btn-ghost" style={{ fontSize: 12, color: 'var(--amber)' }}>
            Undo Last Batch
          </button>
        )}
        <Counts counts={counts} />
      </div>

      {/* Confirm modal */}
      {showConfirm && (
        <ConfirmModal
          groups={groups.filter(g => checked.has(groupKey(g)))}
          onProceed={handleConfirmSelected}
          onCancel={() => setShowC(false)}
          loading={confirming}
        />
      )}

      {/* Scroll area */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
        {suggestions.map(s => (
          <SuggestionRow
            key={s.id}
            suggestion={s}
            onAccept={() => onAcceptSuggestion(s.id)}
            onDismiss={() => onDismissSuggestion(s.id)}
          />
        ))}

        {groups.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>📂</div>
            <div>No files awaiting review.</div>
            <div style={{ marginTop: 6, fontSize: 12 }}>Drag files onto the Sortilege window to begin.</div>
          </div>
        )}

        {groups.map(group => (
          <GroupRow
            key={groupKey(group)}
            group={group}
            checked={checked.has(groupKey(group))}
            onToggle={() => toggleGroup(groupKey(group))}
            onConfirmSingle={async () => {
              const fileIds = group.files.map(f => f.id)
              await onConfirm(fileIds, {})
            }}
          />
        ))}
      </div>
    </div>
  )
}

function groupKey(g) {
  return `${g.node_id ?? 'null'}:${g.planned_op}`
}

function Counts({ counts }) {
  return (
    <div style={{ display: 'flex', gap: 10, color: 'var(--text-secondary)', fontSize: 12 }}>
      {counts.held > 0       && <span>{counts.held} held</span>}
      {counts.budget_paused > 0 && <span className="amber">{counts.budget_paused} paused</span>}
      {counts.errors > 0     && <span className="red">{counts.errors} errors</span>}
    </div>
  )
}

function SuggestionRow({ suggestion, onAccept, onDismiss }) {
  const payload = suggestion.payload ?? {}
  const label = suggestion.kind === 'folder'
    ? `Create folder: ${payload.proposed_path ?? ''}  — ${suggestion.evidence_count} files`
    : `Rule: .${payload.ext} → ${payload.destination}  (${suggestion.evidence_count} corrections)`

  return (
    <div style={{
      borderLeft: '3px solid var(--accent)',
      background: 'var(--bg-card)',
      borderRadius: 'var(--radius)',
      padding: '7px 12px',
      marginBottom: 4,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
    }}>
      <span style={{ color: 'var(--accent)', marginRight: 4 }}>✦</span>
      <span style={{ flex: 1, color: 'var(--text-secondary)', fontSize: 12 }}>{label}</span>
      <button className="btn-primary" style={{ fontSize: 11, padding: '3px 10px' }} onClick={onAccept}>Accept</button>
      <button className="btn-ghost" style={{ fontSize: 11, padding: '3px 10px' }} onClick={onDismiss}>Dismiss</button>
    </div>
  )
}

function ConfirmModal({ groups, onProceed, onCancel, loading }) {
  const moved  = groups.filter(g => g.planned_op === 'move').reduce((s, g) => s + g.file_count, 0)
  const copied = groups.filter(g => g.planned_op === 'copy').reduce((s, g) => s + g.file_count, 0)
  const skipped = groups.filter(g => g.kind === 'dupe').reduce((s, g) => s + g.file_count, 0)

  return (
    <div style={{
      position: 'fixed', inset: 0,
      background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 200,
    }}>
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: 24,
        width: 400,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 12 }}>Confirm batch</div>
        <div style={{ color: 'var(--text-secondary)', marginBottom: 16, lineHeight: 1.8 }}>
          {moved  > 0 && <div>Move {moved} files</div>}
          {copied > 0 && <div>Copy {copied} files</div>}
          {skipped > 0 && <div>Skip {skipped} duplicates</div>}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn-ghost" onClick={onCancel} disabled={loading}>Cancel</button>
          <button className="btn-primary" onClick={onProceed} disabled={loading}>
            {loading ? 'Working…' : 'Proceed'}
          </button>
        </div>
      </div>
    </div>
  )
}
