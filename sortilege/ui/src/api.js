const BASE = ''

async function req(method, path, body) {
  const opts = { method, headers: {} }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(BASE + path, opts)
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(text)
  }
  return res.json()
}

export const api = {
  getFiles:        (state = 'held')          => req('GET', `/api/files?state=${state}`),
  getTaxonomy:     ()                         => req('GET', '/api/taxonomy'),
  getBatches:      (limit = 10)              => req('GET', `/api/batches?limit=${limit}`),
  getConfig:       ()                         => req('GET', '/api/config'),

  intake:          (paths)                   => req('POST', '/api/intake', { paths }),

  confirm:         (file_ids, overrides = {}) => req('POST', '/api/confirm', { file_ids, overrides }),
  undo:            (batch_id)                => req('POST', '/api/undo', { batch_id }),

  createFolder:    (parent_id, name)         => req('POST', '/api/folder', { parent_id, name }),

  acceptSuggestion:  (id)                    => req('POST', `/api/suggestion/${id}/accept`),
  dismissSuggestion: (id)                    => req('POST', `/api/suggestion/${id}/dismiss`),

  updateConfig:    (patch)                   => req('POST', '/api/config', patch),

  // setup-specific
  validatePath:    (output_root)             => req('POST', '/api/setup/validate-path', { output_root }),
  validateKey:     (api_key)                 => req('POST', '/api/setup/validate-key', { api_key }),
  checkEnv:        ()                        => req('GET', '/api/setup/check-env'),
  setupFinish:     (data)                    => req('POST', '/api/setup/finish', data),
}

export function sseConnect(onEvent) {
  const es = new EventSource('/api/sse/progress')
  es.addEventListener('file_classified', e => onEvent('file_classified', JSON.parse(e.data)))
  es.addEventListener('batch_ready',     e => onEvent('batch_ready',     JSON.parse(e.data)))
  es.addEventListener('budget_paused',   e => onEvent('budget_paused',   JSON.parse(e.data)))
  return () => es.close()
}
