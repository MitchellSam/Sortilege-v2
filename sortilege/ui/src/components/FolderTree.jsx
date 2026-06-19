import { useState } from 'react'

export default function FolderTree({ nodes }) {
  const roots = buildTree(nodes)

  return (
    <div style={{
      width: 280,
      minWidth: 180,
      borderRight: '1px solid var(--border)',
      background: 'var(--bg-panel)',
      overflowY: 'auto',
      flexShrink: 0,
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div style={{ padding: '10px 12px 6px', color: 'var(--text-secondary)', fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        Folders
      </div>
      <div style={{ flex: 1 }}>
        {roots.map(n => <TreeNode key={n.id} node={n} depth={0} />)}
      </div>
    </div>
  )
}

function TreeNode({ node, depth }) {
  const [open, setOpen] = useState(depth === 0)
  const hasChildren = node.children?.length > 0
  const isUnsorted = node.rel_path === 'unsorted'

  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: `3px 8px 3px ${8 + depth * 16}px`,
          cursor: 'pointer',
          color: isUnsorted ? 'var(--text-muted)' : 'var(--text-primary)',
          fontStyle: isUnsorted ? 'italic' : undefined,
          borderRadius: 3,
          margin: '0 4px',
        }}
        onClick={() => hasChildren && setOpen(o => !o)}
      >
        {hasChildren ? (
          <span style={{ marginRight: 4, color: 'var(--text-secondary)', fontSize: 10 }}>
            {open ? '▾' : '▸'}
          </span>
        ) : <span style={{ marginRight: 4, width: 14, display: 'inline-block' }} />}
        <span style={{ marginRight: 6 }}>📁</span>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.name}
        </span>
      </div>
      {open && hasChildren && (
        <div>
          {node.children.map(c => <TreeNode key={c.id} node={c} depth={depth + 1} />)}
        </div>
      )}
    </div>
  )
}

function buildTree(nodes) {
  const map = {}
  nodes.forEach(n => { map[n.id] = { ...n, children: [] } })
  const roots = []
  nodes.forEach(n => {
    if (n.parent_id == null) roots.push(map[n.id])
    else if (map[n.parent_id]) map[n.parent_id].children.push(map[n.id])
  })
  return roots
}
