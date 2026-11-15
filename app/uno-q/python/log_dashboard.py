"""Dependency-free, thread-safe offline status dashboard for ParkSight.

HTTP is intentionally unauthenticated: the Wi-Fi hotspot password is the
network boundary. Do not connect untrusted clients or publish port 5001 to
other networks, since plate text may appear in the logs.
"""

from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from threading import Lock, Thread
from time import monotonic
from urllib.parse import parse_qs, urlsplit


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0a121c">
<title>ParkSight · Live monitor</title>
<style>
:root { color-scheme: dark; --bg:#0a121c; --panel:#131f2c; --border:#293c4c; --muted:#9bb0bd; --accent:#53dbc8; --text:#ecf6fb }
* { box-sizing: border-box }
body { background: radial-gradient(circle at 95% 0%,#122f3c 0%,var(--bg) 55%); color:var(--text); font: 15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0 }
main { max-width:1000px; padding:26px 18px 50px; margin:auto }
header { display:flex; flex-wrap:wrap; justify-content:space-between; gap:14px; align-items:center; margin-bottom:24px }
h1 { font-size:28px; margin:0; letter-spacing:-.5px } h1 b {color:var(--accent)}
small, .muted { color:var(--muted) } .pill { padding:5px 12px; border-radius:20px; background:#1a3f3e; color:#a4f5d8; font-weight:600 }
.grid {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-bottom:22px}
.panel,.metric {border:1px solid var(--border); border-radius:14px; background:var(--panel)}
.metric {padding:15px 18px}.metric span { display:block; color:var(--muted); font-size:13px; margin-bottom:5px }.metric strong { font-size:23px; overflow-wrap:anywhere }
.panel { overflow:hidden }.toolbar {display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; padding:15px 17px; border-bottom:1px solid var(--border)}
.toolbar h2 {margin:0; font-size:18px} .actions { display:flex; flex-wrap:wrap; align-items:center; gap:12px }
#garage {margin-bottom:22px}
#garage-form {padding:15px 17px; display:grid; gap:12px}
#garage-form[hidden] {display:none}
#garage-form label { display:grid; gap:4px; min-width: min(100%, 220px) }
#garage-form input {font:inherit; padding:6px 8px; border:1px solid var(--border); border-radius:6px}
#garage-result { margin:0; min-height:1.5em }
button {color:var(--text); background:#264354; border:1px solid #426679; border-radius:8px; padding:7px 11px; cursor:pointer}
button:hover {background:#345669}.switch {cursor:pointer; color:var(--muted); font-size:13px}
pre {font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; margin:0; white-space:pre-wrap; overflow-wrap:anywhere; padding:13px 17px; min-height:280px; max-height:58vh; overflow:auto}
.entry {margin:0 0 5px} .ts {color:#8ea4b3} .lvl { color:#80d8ca } .warn {color:#ffcf82} .err {color:#ff91a3}
footer {margin-top:14px; color:var(--muted); font-size:12px}
@media(max-width:620px) {.grid {grid-template-columns:1fr 1fr} .metric strong {font-size:20px} h1 {font-size:25px}}
</style></head><body><main>
<header><div><h1>Park<b>Sight</b></h1><small>UNO Q · Local monitoring, no internet required</small></div><span id="connection" class="pill">Connecting…</span></header>
<section class="grid" aria-label="Live status">
<div class="metric"><span>Parking stall</span><strong id="stall">—</strong></div>
<div class="metric"><span>Camera</span><strong id="camera">—</strong></div>
<div class="metric"><span>Last plate</span><strong id="plate">—</strong></div>
<div class="metric"><span>Issuing state (guess)</span><strong id="plate-state">—</strong></div>
<div class="metric"><span>Motion triggers</span><strong id="motion">0</strong></div>
<div class="metric"><span>OCR attempts</span><strong id="ocr">0</strong></div>
<div class="metric"><span>Uptime</span><strong id="uptime">—</strong></div>
</section>
<section id="garage" class="panel" hidden>
<div class="toolbar"><h2>Garage</h2><span id="lakebase-sync" class="muted">Connecting…</span></div>
<form id="garage-form" autocomplete="off">
<div class="actions">
<label>Lakebase plate key <input id="garage-key" maxlength="32" required
 autocomplete="off" autocapitalize="characters" spellcheck="false"></label>
<label>Operator token <input id="garage-token" type="password" required
 maxlength="128" autocomplete="off"></label>
</div>
<div class="actions">
<button type="submit" value="check">Check</button><button type="submit" value="book">Book</button>
<button type="submit" value="enter">Enter</button><button type="submit" value="exit">Exit</button>
<button type="submit" value="cancel">Cancel booking</button>
</div>
<p id="garage-result" role="status"></p>
</form></section>
<section class="panel"><div class="toolbar"><h2>Live application logs</h2><div class="actions">
<label class="switch"><input type="checkbox" id="autoscroll" checked> Auto-scroll</label>
<a href="/recognition-debug" target="_blank" rel="noopener" style="color:var(--text)">Latest recognition debug</a>
<button id="download" type="button">Download logs</button><button id="clear" type="button">Clear display</button>
</div></div><pre id="logs" role="log" aria-live="off">Waiting for events…</pre></section>
<footer>Updates every second · Display buffers the latest 600 entries · Network password protects access to this local HTTP page, but HTTP itself is not encrypted.</footer>
</main><script>
(() => {
 const $ = id => document.getElementById(id);
 const log = $('logs'); let last = 0; let lines = []; let connected = false;
 let prefilledPlate = null;
 const fmt = n => String(n).padStart(2,'0');
 const formatTime = iso => { const d = new Date(iso); return `${fmt(d.getHours())}:${fmt(d.getMinutes())}:${fmt(d.getSeconds())}`; };
 function render() { log.textContent = lines.join('\n') || 'No logs yet'; if ($('autoscroll').checked) log.scrollTop=log.scrollHeight; }
 function seconds(s) {s=Math.floor(s||0); return `${Math.floor(s/3600)}h ${fmt(Math.floor(s%3600/60))}m ${fmt(s%60)}s`;}
 async function poll(){
  try {
   const res=await fetch('/api/logs?after='+encodeURIComponent(last),{cache:'no-store'});
   if(!res.ok) throw new Error('HTTP '+res.status);
   const data=await res.json();
   if(data.reset || (data.last_id < last)){ last=0; lines=[]; }
   for(const e of data.entries){ last=Math.max(last,e.id); lines.push(`[${formatTime(e.time)}] ${e.level.padEnd(7)} ${e.message}`); }
   if(lines.length>600) lines=lines.slice(-600);
   render(); $('stall').textContent=data.status.stall; $('camera').textContent=data.status.camera;
   $('plate').textContent=data.status.last_plate||'—';
   $('plate-state').textContent=data.status.last_plate ? data.status.last_plate_state || 'Unknown' : '—';
   $('motion').textContent=data.status.motion_events;
   $('ocr').textContent=data.status.ocr_attempts; $('uptime').textContent=seconds(data.status.uptime_seconds);
   $('garage').hidden = !data.status.lakebase_enabled && data.status.lakebase_sync === 'Disabled';
   $('garage-form').hidden = !data.status.lakebase_enabled;
   const spot = data.status.lakebase_spot;
   $('lakebase-sync').textContent = spot ? spot + ' · ' + data.status.lakebase_sync : data.status.lakebase_sync;
   if(data.status.last_plate && data.status.last_plate !== prefilledPlate &&
      document.activeElement !== $('garage-key')){
     $('garage-key').value = data.status.last_plate;
     prefilledPlate = data.status.last_plate;
   }
   $('connection').textContent='Live · Connected'; connected=true;
  }catch(e){$('connection').textContent='Disconnected';connected=false; }
 }
 $('garage-form').onsubmit=async event=>{
   event.preventDefault();
   const action=event.submitter?.value || 'check';
   const key=$('garage-key').value.trim();
   const buttons=$('garage-form').querySelectorAll('button');
   buttons.forEach(button=>button.disabled=true);
   $('garage-result').textContent='Working…';
   try {
     const response=await fetch('/api/garage', {
       method:'POST',
       headers:{'Content-Type':'application/json', 'X-ParkSight-Token':$('garage-token').value},
       body:JSON.stringify({action, plate_key:key})
     });
     const result=await response.json();
     $('garage-result').textContent=key+' · '+result.message;
   } catch {
     $('garage-result').textContent=action === 'check' ? 'Could not check the plate.' :
       'Write outcome unknown. Check the plate before retrying.';
   } finally {
     buttons.forEach(button=>button.disabled=false);
   }
 };
 $('download').onclick=()=>{const blob=new Blob([lines.join('\n')+'\n'],{type:'text/plain'});const u=URL.createObjectURL(blob);const a=document.createElement('a');a.href=u;a.download='parksight-logs.txt';a.click();URL.revokeObjectURL(u);};
 $('clear').onclick=()=>{lines=[];render();};
 poll();setInterval(poll,1000);
})();
</script></body></html>'''


class LiveLogStore:
    def __init__(self, limit=600):
        self._logs = deque(maxlen=limit)
        self._lock = Lock()
        self._serial = 0
        self._boot = monotonic()
        self._status = {
            "stall": "unknown", "camera": "starting", "last_plate": None, "last_plate_state": None,
            "motion_events": 0, "ocr_attempts": 0, "plate_reads": 0,
            "lakebase_enabled": False, "lakebase_spot": None, "lakebase_sync": "Disabled",
        }

    def add(self, record):
        with self._lock:
            self._serial += 1
            self._logs.append({
                "id": self._serial,
                "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname,
                "message": logging.Formatter("%(message)s").format(record),
            })

    def set(self, **changes):
        with self._lock:
            self._status.update(changes)

    def increment(self, key):
        with self._lock:
            self._status[key] += 1

    def snapshot(self, after=0):
        with self._lock:
            # A new client starts at zero and receives the retained history.
            # If history rolled over, return it all to avoid silent gaps.
            oldest = self._logs[0]["id"] if self._logs else self._serial + 1
            reset = (after > self._serial)
            if (after and after < oldest - 1) or reset:
                entries = list(self._logs)
            else:
                entries = [x for x in self._logs if x["id"] > after]
            status = dict(self._status)
            serial = self._serial
        status["uptime_seconds"] = int(monotonic() - self._boot)
        return {"entries": entries, "last_id": serial, "reset": reset,
                "status": status}


class _BufferHandler(logging.Handler):
    def __init__(self, store):
        super().__init__(logging.INFO)
        self.store = store

    def emit(self, record):
        self.store.add(record)


def configure_logging(store):
    """Mirror app logs to both App Lab's Python console and the web dashboard."""
    logger = logging.getLogger("parksight")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        import sys
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logger.addHandler(console)
        logger.addHandler(_BufferHandler(store))
    return logger


def start_web_server(store, log, address="0.0.0.0", port=5001, *, debug_report, lakebase=None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if urlsplit(self.path).path != "/api/garage":
                self.send_error(404, "Not Found")
                return
            if lakebase is None:
                self.send_json(503, {"message": "Lakebase integration is disabled."})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096 or self.headers.get_content_type() != "application/json":
                    raise ValueError("Invalid request")
                self.connection.settimeout(5)
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Expected a request object")
            except (ValueError, OSError):
                self.send_json(400, {"message": "Invalid garage request."})
                return
            status, result = lakebase.garage(
                self.headers.get("X-ParkSight-Token", ""), data.get("action"), data.get("plate_key")
            )
            self.send_json(status, result)

        def send_json(self, status, value):
            self.send_payload(status, json.dumps(value).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                payload = PAGE.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            elif parsed.path == "/api/logs":
                try:
                    after = max(0, int(parse_qs(parsed.query).get("after", ["0"])[0]))
                except ValueError:
                    after = 0
                payload = json.dumps(store.snapshot(after)).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif parsed.path == "/health":
                payload = b'{"ok":true,"service":"parksight-log-dashboard"}'
                content_type = "application/json; charset=utf-8"
            elif parsed.path == "/recognition-debug":
                try:
                    payload = debug_report.read_bytes()
                except FileNotFoundError:
                    self.send_error(404, "No recognition debug report yet. Trigger motion and reload.")
                    return
                except OSError:
                    log.exception("Could not read the recognition debug report")
                    self.send_error(500, "Could not read the recognition debug report")
                    return
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404, "Not Found")
                return
            self.send_payload(200, payload, content_type)

        def send_payload(self, status, payload, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, fmt, *args):
            # Avoid adding a log message for every 1-second browser refresh.
            return

    server = ThreadingHTTPServer((address, port), Handler)
    server.daemon_threads = True
    Thread(target=server.serve_forever, daemon=True,
           name="parksight-http").start()
    log.info("Offline dashboard listening at http://%s:%d", address, port)
    return server
