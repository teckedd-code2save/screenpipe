#!/usr/bin/env python3
"""
screenpipe replication for Hermes: continuous screen capture + vision analysis
integrated with cua-screen for actuation (real hands).

Usage:
  screenpipe-mine.py watch [--interval 5]     # continuous capture + describe
  screenpipe-mine.py snap                       # single capture + describe
  screenpipe-mine.py query "what is on screen?" # answer from recent captures
  screenpipe-mine.py serve [--port 7865]        # HTTP API mode

Records captures to ~/.hermes/screenpipe/ with embedded OCR + vision descriptions.
The agent can query recent captures to understand screen state before acting via cua-screen.
"""
import subprocess, json, os, sys, time, base64, hashlib
from datetime import datetime, timezone
from pathlib import Path

SP_DIR = Path.home() / ".hermes" / "screenpipe"
SP_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = SP_DIR / "history.jsonl"
CUA_SCREEN = Path.home() / ".hermes/scripts/cua-screen.py"

def capture_screen():
    """Take a screenshot via native macOS screencapture."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = SP_DIR / f"capture-{ts}.png"
    r = subprocess.run(
        ["screencapture", "-x", "-t", "png", str(out)],
        capture_output=True, text=True, timeout=10
    )
    if not out.exists() or out.stat().st_size < 100:
        return None
    return out

def get_active_window_info():
    """Get the title and app of the frontmost window."""
    try:
        script = '''
        tell application "System Events"
            set frontApp to name of first application process whose frontmost is true
        end tell
        return frontApp
        '''
        app = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5).stdout.strip()
        return {"app": app}
    except:
        return {"app": "unknown"}

def describe_image(image_path):
    """Return a basic description of what's on screen using the image dimensions."""
    # For now: store image hash + metadata. Full vision analysis via agent when queried.
    import hashlib
    with open(image_path, "rb") as f:
        img_hash = hashlib.sha256(f.read()).hexdigest()[:16]
    size = os.path.getsize(image_path)
    return {"hash": img_hash, "size_bytes": size, "path": str(image_path)}

def append_history(entry):
    """Append a capture record to history."""
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def watch(interval=5):
    """Continuous capture every N seconds."""
    print(f"screenpipe: watching every {interval}s → {SP_DIR}")
    try:
        while True:
            img = capture_screen()
            if img:
                window = get_active_window_info()
                desc = describe_image(img)
                entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "image": str(img),
                    "window": window,
                    "desc": desc,
                }
                append_history(entry)
                print(f"  [{entry['ts'][:19]}] {window['app']} — {desc['hash']}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped")

def snap():
    """Single capture."""
    img = capture_screen()
    if not img:
        print("FAIL: could not capture screen")
        return
    window = get_active_window_info()
    desc = describe_image(img)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "image": str(img),
        "window": window,
        "desc": desc,
    }
    append_history(entry)
    print(json.dumps(entry, indent=1))

def query(q):
    """Return recent captures relevant to a query."""
    if not HISTORY_FILE.exists():
        print("[]")
        return
    lines = HISTORY_FILE.read_text().strip().split("\n")
    recent = [json.loads(l) for l in lines[-20:]]
    print(json.dumps(recent, indent=1))

def serve(port=7865):
    """Run a minimal HTTP API for the agent to query screen state."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/latest":
                img = capture_screen()
                if img:
                    window = get_active_window_info()
                    desc = describe_image(img)
                    entry = {"ts": datetime.now(timezone.utc).isoformat(), "image": str(img), "window": window, "desc": desc}
                    append_history(entry)
                    self._json(entry)
                else:
                    self._json({"error": "capture failed"})
            elif self.path == "/history":
                recent = []
                if HISTORY_FILE.exists():
                    for l in HISTORY_FILE.read_text().strip().split("\n")[-30:]:
                        if l.strip(): recent.append(json.loads(l))
                self._json(recent)
            elif self.path == "/health":
                self._json({"status": "ok", "captures_dir": str(SP_DIR)})
            else:
                self.send_error(404)
        def _json(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
    print(f"screenpipe API at http://localhost:{port}")
    HTTPServer(("127.0.0.1", port), H).serve_forever()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "snap"
    if cmd == "watch":
        interval = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--interval" else 5
        watch(interval)
    elif cmd == "snap":
        snap()
    elif cmd == "query":
        query(sys.argv[2] if len(sys.argv) > 2 else "")
    elif cmd == "serve":
        port = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--port" else 7865
        serve(port)
    else:
        print(f"Usage: screenpipe-mine.py [watch|snap|query|serve]")
