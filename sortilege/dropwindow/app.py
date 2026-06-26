"""Win32 native drop-target window.

Uses WM_DROPFILES / DragAcceptFiles for reliable file-path delivery.
The browser File API does not expose local paths in WebView2 contexts,
so pywebview is replaced with a direct Win32 window via ctypes.
"""

import ctypes
import ctypes.wintypes
import json
import threading
import urllib.request
from urllib.error import URLError

_API_URL = "http://localhost:8000/api/intake"

# ---------------------------------------------------------------------------
# Win32 bindings
# ---------------------------------------------------------------------------
_u32  = ctypes.windll.user32
_g32  = ctypes.windll.gdi32
_k32  = ctypes.windll.kernel32
_sh32 = ctypes.windll.shell32

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong,
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize",        ctypes.c_uint),
        ("style",         ctypes.c_uint),
        ("lpfnWndProc",   WNDPROC),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     ctypes.wintypes.HINSTANCE),
        ("hIcon",         ctypes.wintypes.HICON),
        ("hCursor",       ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HBRUSH),
        ("lpszMenuName",  ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
        ("hIconSm",       ctypes.wintypes.HICON),
    ]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc",         ctypes.wintypes.HDC),
        ("fErase",      ctypes.wintypes.BOOL),
        ("rcPaint",     ctypes.wintypes.RECT),
        ("fRestore",    ctypes.wintypes.BOOL),
        ("fIncUpdate",  ctypes.wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


# Constants
WM_DESTROY        = 0x0002
WM_PAINT          = 0x000F
WM_ERASEBKGND     = 0x0014
WM_DROPFILES      = 0x0233
WM_TIMER          = 0x0113
CS_HREDRAW        = 0x0002
CS_VREDRAW        = 0x0001
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE        = 0x10000000
WS_EX_TOPMOST     = 0x00000008
WS_EX_ACCEPTFILES = 0x00000010
DT_CENTER         = 0x0001
DT_VCENTER        = 0x0004
DT_SINGLELINE     = 0x0020
TRANSPARENT_MODE  = 1
TIMER_ANIM        = 1

# Colors: COLORREF = R | (G << 8) | (B << 16)
def _rgb(r, g, b): return r | (g << 8) | (b << 16)

_C = {
    "idle":    _rgb(0x1a, 0x1a, 0x2e),
    "proc":    _rgb(0x1a, 0x1a, 0x20),
    "success": _rgb(0x1a, 0x3a, 0x1a),
    "error":   _rgb(0x3a, 0x1a, 0x1a),
    "fg":      _rgb(0xe0, 0xe0, 0xe0),
    "bar":     _rgb(0x78, 0x78, 0xc8),
    "bar_bg":  _rgb(0x2a, 0x2a, 0x3a),
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_hwnd  = None
_label = "Drop files here"
_state = "idle"   # idle | processing | success | error
_anim  = 0.0      # 0.0-1.0 cycling; drives indeterminate bar


def _repaint():
    if _hwnd:
        _u32.InvalidateRect(_hwnd, None, True)


def _set(state, label):
    global _state, _label
    _state, _label = state, label
    _repaint()


def _reset():
    _set("idle", "Drop files here")


def _send_paths(paths):
    def _work():
        try:
            body = json.dumps({"paths": paths}).encode()
            req = urllib.request.Request(
                _API_URL, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read())
            n = d.get("accepted", 0)
            _set("success", f"{n} file{'s' if n != 1 else ''} queued")
        except Exception:
            _set("error", "Server unreachable")
            threading.Timer(3.0, _reset).start()
    threading.Thread(target=_work, daemon=True).start()


# ---------------------------------------------------------------------------
# Window procedure
# ---------------------------------------------------------------------------
def _wndproc(hwnd, msg, wparam, lparam):
    global _anim

    if msg == WM_DESTROY:
        _u32.KillTimer(hwnd, TIMER_ANIM)
        _u32.PostQuitMessage(0)
        return 0

    if msg == WM_TIMER:
        if _state == "processing":
            _anim = (_anim + 0.04) % 1.0
            _repaint()
        return 0

    if msg == WM_DROPFILES:
        count = _sh32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
        paths = []
        for i in range(count):
            n = _sh32.DragQueryFileW(wparam, i, None, 0) + 1
            buf = ctypes.create_unicode_buffer(n)
            _sh32.DragQueryFileW(wparam, i, buf, n)
            paths.append(buf.value)
        _sh32.DragFinish(wparam)
        if paths:
            n = len(paths)
            _set("processing", f"Classifying {n} file{'s' if n != 1 else ''}…")
            _u32.SetTimer(hwnd, TIMER_ANIM, 40, None)
            _send_paths(paths)
        return 0

    if msg == WM_ERASEBKGND:
        return 1

    if msg == WM_PAINT:
        ps = _PAINTSTRUCT()
        hdc = _u32.BeginPaint(hwnd, ctypes.byref(ps))
        rc  = ctypes.wintypes.RECT()
        _u32.GetClientRect(hwnd, ctypes.byref(rc))
        w, h = rc.right, rc.bottom
        BAR_H = 4

        # Background
        bg = _g32.CreateSolidBrush(_C.get(_state, _C["idle"]))
        _u32.FillRect(hdc, ctypes.byref(rc), bg)
        _g32.DeleteObject(bg)

        # Progress bar strip at bottom
        bb = _g32.CreateSolidBrush(_C["bar_bg"])
        bar_bg_rc = ctypes.wintypes.RECT(0, h - BAR_H, w, h)
        _u32.FillRect(hdc, ctypes.byref(bar_bg_rc), bb)
        _g32.DeleteObject(bb)

        if _state == "success":
            bf = _g32.CreateSolidBrush(_C["bar"])
            _u32.FillRect(hdc, ctypes.byref(ctypes.wintypes.RECT(0, h - BAR_H, w, h)), bf)
            _g32.DeleteObject(bf)
        elif _state == "processing":
            bar_w = max(40, w // 3)
            travel = w - bar_w
            t = _anim * 2.0
            pos = int((t if t < 1.0 else 2.0 - t) * travel)
            bf = _g32.CreateSolidBrush(_C["bar"])
            _u32.FillRect(hdc, ctypes.byref(
                ctypes.wintypes.RECT(pos, h - BAR_H, pos + bar_w, h)
            ), bf)
            _g32.DeleteObject(bf)

        # Label
        font = _g32.CreateFontW(-14, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Segoe UI")
        old  = _g32.SelectObject(hdc, font)
        _g32.SetTextColor(hdc, _C["fg"])
        _g32.SetBkMode(hdc, TRANSPARENT_MODE)
        text_rc = ctypes.wintypes.RECT(8, 0, w - 8, h - BAR_H)
        _u32.DrawTextW(hdc, _label, -1, ctypes.byref(text_rc),
                       DT_CENTER | DT_VCENTER | DT_SINGLELINE)
        _g32.SelectObject(hdc, old)
        _g32.DeleteObject(font)

        _u32.EndPaint(hwnd, ctypes.byref(ps))
        return 0

    return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run() -> None:
    global _hwnd

    hinstance = _k32.GetModuleHandleW(None)
    cls_name  = "SortilegeDropWindow"

    wc = _WNDCLASSEXW()
    wc.cbSize       = ctypes.sizeof(_WNDCLASSEXW)
    wc.style        = CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc  = WNDPROC(_wndproc)
    wc.hInstance    = hinstance
    wc.hbrBackground = ctypes.cast(
        _g32.CreateSolidBrush(_C["idle"]), ctypes.wintypes.HBRUSH
    )
    wc.lpszClassName = cls_name

    if not _u32.RegisterClassExW(ctypes.byref(wc)):
        raise RuntimeError("RegisterClassExW failed")

    hwnd = _u32.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_ACCEPTFILES,
        cls_name, "Sortilege",
        WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        100, 100, 240, 240,
        None, None, hinstance, None,
    )
    if not hwnd:
        raise RuntimeError("CreateWindowExW failed")
    _hwnd = hwnd

    _sh32.DragAcceptFiles(hwnd, True)

    m = ctypes.wintypes.MSG()
    while _u32.GetMessageW(ctypes.byref(m), None, 0, 0) > 0:
        _u32.TranslateMessage(ctypes.byref(m))
        _u32.DispatchMessageW(ctypes.byref(m))


if __name__ == "__main__":
    run()
