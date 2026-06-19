"""Server entry point. Run via: .venv\Scripts\python.exe -m uvicorn sortilege.api.routes:app --host 127.0.0.1 --port 8000"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn


def start_drop_window():
    time.sleep(3)
    try:
        from sortilege.dropwindow.app import run
        run()
    except Exception as e:
        print(f"Drop window failed to start: {e}", file=sys.stderr)


if __name__ == "__main__":
    t = threading.Thread(target=start_drop_window, daemon=True)
    t.start()
    uvicorn.run(
        "sortilege.api.routes:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
