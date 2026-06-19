import { useState } from 'react'

const THRESHOLD = 0.85

export default function GroupRow({ group, checked, onToggle, onConfirmSingle }) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail]     = useState(null)

  const conf = group.min_confidence ?? 0
  const confColor = conf >= THRESHOLD ? 'var(--green)' : 'var(--amber)'
  const isDupe  = group.kind === 'dupe'
  const isError = group.kind === 'error'

  const label = isDupe
    ? 'dupe — already filed'
    : isError
    ? 'error — unreadable'
    : group.rel_path || '(unclassified)'

  return (
    <div style={{
      background: 'var(--bg-card)',
      borderRadius: 'var(--radius)',
      marginBottom: 3,
      border: `1px solid ${isError ? 'var(--red)' : 'var(--border)'}`,
    }}>
      {/* Collapsed header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        padding: '6px 10px',
        gap: 8,
        cursor: 'pointer',
      }}>
        {!isError && (
          <input
            type="checkbox"
            checked={checked}
            onChange={onToggle}
            onClick={e => e.stopPropagation()}
            style={{ width: 14, height: 14, accentColor: 'var(--accent)', flexShrink: 0 }}
          />
        )}
        {isError && <span style={{ color: 'var(--red)', fontSize: 14 }}>⚠</span>}
        <span style={{ color: 'var(--text-secondary)', minWidth: 50, textAlign: 'right', fontSize: 12 }}>
          {group.file_count}
        </span>
        <span style={{ color: 'var(--text-secondary)' }}>→</span>
        <span className="mono" style={{
          flex: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontSize: 12,
          color: isDupe ? 'var(--text-muted)' : 'var(--text-primary)',
          fontStyle: isDupe ? 'italic' : undefined,
        }}>
          {label}
        </span>
        {!isError && !isDupe && (
          <span style={{ color: confColor, fontSize: 11, minWidth: 40, textAlign: 'right' }}>
            {Math.round(conf * 100)}%
          </span>
        )}
        {!isError && (
          <button
            className="btn-primary"
            style={{ fontSize: 11, padding: '3px 10px', flexShrink: 0 }}
            onClick={e => { e.stopPropagation(); onConfirmSingle() }}
          >
            CONFIRM
          </button>
        )}
        <span
          style={{ color: 'var(--text-secondary)', fontSize: 12, userSelect: 'none', padding: '0 4px' }}
          onClick={() => setExpanded(e => !e)}
        >
          {expanded ? '▾' : '▸'}
        </span>
      </div>

      {/* Expanded file list */}
      {expanded && (
        <div style={{ borderTop: '1px solid var(--border)' }}>
          {group.files.map(f => (
            <FileRow key={f.id} file={f} confColor={confColor} onClick={() => setDetail(f)} />
          ))}
          {detail && <DetailPanel file={detail} onClose={() => setDetail(null)} />}
        </div>
      )}
    </div>
  )
}

function FileRow({ file, onClick }) {
  const conf = file.confidence ?? 0
  const confColor = conf >= THRESHOLD ? 'var(--green)' : 'var(--amber)'
  const size = formatSize(file.size)
  const mtime = file.mtime ? file.mtime.slice(0, 10) : ''

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '4px 12px 4px 28px',
        gap: 10,
        borderBottom: '1px solid var(--border)',
        cursor: 'pointer',
      }}
      onClick={onClick}
    >
      <span className="mono" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }}>
        {file.filename ?? file.source_path?.split('\\').pop()}
      </span>
      <span style={{ color: confColor, fontSize: 11, minWidth: 36, textAlign: 'right' }}>{Math.round(conf * 100)}%</span>
      <span style={{ color: 'var(--text-secondary)', fontSize: 11, minWidth: 52, textAlign: 'right' }}>{size}</span>
      <span style={{ color: 'var(--text-secondary)', fontSize: 11, minWidth: 72 }}>{mtime}</span>
    </div>
  )
}

function DetailPanel({ file, onClose }) {
  const conf = file.confidence ?? 0
  const tierLabel = file.tier != null ? `Tier ${file.tier}` : ''

  return (
    <div style={{
      position: 'fixed',
      top: 40, right: 0, bottom: 0,
      width: 380,
      background: 'var(--bg-panel)',
      borderLeft: '1px solid var(--border)',
      overflowY: 'auto',
      padding: 20,
      zIndex: 50,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontWeight: 600 }}>{file.filename ?? 'File Detail'}</span>
        <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', fontSize: 16 }}>✕</button>
      </div>
      <Row label="Source" value={file.source_path} mono />
      <Row label="Size"   value={formatSize(file.size)} />
      <Row label="Modified" value={file.mtime?.slice(0, 10)} />
      <Row label="Tier"   value={tierLabel} />
      <Row label="Confidence" value={`${Math.round(conf * 100)}%`} />
      {file.reasoning && (
        <div style={{ marginTop: 12 }}>
          <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 4 }}>REASONING</div>
          <div style={{ color: 'var(--text-primary)', fontSize: 12, lineHeight: 1.6 }}>{file.reasoning}</div>
        </div>
      )}
      {file.dupe_of_file_id && (
        <div style={{ marginTop: 12, color: 'var(--text-secondary)', fontSize: 12 }}>
          Duplicate of file ID {file.dupe_of_file_id}
        </div>
      )}
    </div>
  )
}

function Row({ label, value, mono }) {
  if (!value) return null
  return (
    <div style={{ marginBottom: 8 }}>
      <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{label}: </span>
      <span className={mono ? 'mono' : ''} style={{ fontSize: 12 }}>{value}</span>
    </div>
  )
}

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}
