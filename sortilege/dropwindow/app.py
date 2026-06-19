"""pywebview always-on-top drop-target window.

Accepts file drag-and-drop and POSTs paths to the FastAPI intake endpoint.
Requires the edgechromium renderer (Windows) for File.path access in DnD events.
"""

import json
import urllib.request
from urllib.error import URLError

import webview

_API_URL = "http://localhost:8000/api/intake"

_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #1a1a2e;
    color: #e0e0e0;
    font-family: system-ui, sans-serif;
    width: 100vw; height: 100vh;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    user-select: none;
    border: 2px dashed #4a4a7a;
    border-radius: 8px;
    transition: background 0.15s, border-color 0.15s;
    cursor: default;
  }
  body.drag-over { background: #2a2a4e; border-color: #7878c8; }
  body.success   { background: #1a3a1a; border-color: #4aaa4a; }
  body.error     { background: #3a1a1a; border-color: #aa4a4a; }
  #icon  { font-size: 30px; margin-bottom: 6px; }
  #label { font-size: 12px; opacity: 0.75; }
  #count { font-size: 11px; opacity: 0.5; margin-top: 4px; }
</style>
</head>
<body id="body">
  <div id="icon">&#128194;</div>
  <div id="label">Drop files here</div>
  <div id="count"></div>
<script>
const body  = document.getElementById('body');
const icon  = document.getElementById('icon');
const label = document.getElementById('label');
const count = document.getElementById('count');

function reset() {
  icon.textContent  = '\u{1F4C2}';
  label.textContent = 'Drop files here';
  count.textContent = '';
  body.className    = '';
}

body.addEventListener('dragover', e => {
  e.preventDefault();
  e.stopPropagation();
  body.classList.add('drag-over');
});

body.addEventListener('dragleave', () => body.classList.remove('drag-over'));

body.addEventListener('drop', e => {
  e.preventDefault();
  e.stopPropagation();
  body.classList.remove('drag-over');

  const paths = [];
  for (const item of e.dataTransfer.items) {
    const f = item.getAsFile();
    if (f && f.path) paths.push(f.path);
  }
  if (paths.length === 0) return;

  count.textContent = paths.length + ' file' + (paths.length === 1 ? '' : 's') + '...';

  window.pywebview.api.intake(paths)
    .then(msg => {
      icon.textContent  = '✓';
      label.textContent = msg;
      count.textContent = '';
      body.classList.add('success');
      setTimeout(reset, 2000);
    })
    .catch(() => {
      icon.textContent  = '⚠';
      label.textContent = 'Server not ready';
      count.textContent = '';
      body.classList.add('error');
      setTimeout(reset, 3000);
    });
});
</script>
</body>
</html>"""


class _Api:
    def intake(self, paths: list[str]) -> str:
        payload = json.dumps({"paths": paths}).encode()
        req = urllib.request.Request(
            _API_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            n = data.get("accepted", 0)
            return f"{n} file{'s' if n != 1 else ''} queued"
        except URLError as exc:
            raise RuntimeError(str(exc)) from exc


def run() -> None:
    """Start the drop window. Blocks until the window is closed."""
    webview.create_window(
        title="Sortilege",
        html=_HTML,
        js_api=_Api(),
        width=220,
        height=220,
        on_top=True,
        frameless=False,
        resizable=False,
        min_size=(150, 150),
    )
    webview.start(gui="edgechromium")
