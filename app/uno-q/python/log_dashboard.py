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
:root { color-scheme: dark; --bg:#0b0d10; --panel:#15181d; --panel-2:#1b1f25; --border:rgba(255,255,255,.08);
 --muted:#8e98a4; --text:#f2f5f8; --accent:#5fe0c4; --accent-soft:rgba(95,224,196,.12); --warn:#ffcf7a; --err:#ff8a9b;
 --radius:18px }
* { box-sizing: border-box }
body { background:radial-gradient(1200px 600px at 85% -10%,#12302e 0%,rgba(18,48,46,0) 60%),var(--bg); color:var(--text);
 font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif; margin:0; -webkit-font-smoothing:antialiased; min-height:100vh }
main { max-width:1080px; padding:40px 24px 56px; margin:auto }
header { display:flex; flex-wrap:wrap; justify-content:space-between; gap:16px; align-items:center; margin-bottom:28px }
h1 { font:600 30px/1.1 -apple-system,BlinkMacSystemFont,"SF Pro Display",sans-serif; margin:0 0 6px; letter-spacing:-.6px } h1 b {color:var(--accent); font-weight:600}
small, .muted { color:var(--muted) }
.pill { display:inline-flex; align-items:center; gap:8px; padding:7px 14px 7px 12px; border-radius:999px; background:var(--accent-soft);
 color:var(--accent); font-weight:600; font-size:13px; border:1px solid rgba(95,224,196,.22) }
.pill::before { content:""; width:7px; height:7px; border-radius:50%; background:currentColor; box-shadow:0 0 0 4px rgba(95,224,196,.18) }
.pill.down { color:var(--err); background:rgba(255,138,155,.1); border-color:rgba(255,138,155,.25) }
.grid {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:20px}
.panel,.metric {border:1px solid var(--border); border-radius:var(--radius); background:linear-gradient(180deg,var(--panel-2),var(--panel))}
.metric {padding:18px 20px; min-height:104px}
.metric span { display:block; color:var(--muted); font-size:12px; font-weight:500; letter-spacing:.06em; text-transform:uppercase; margin-bottom:10px }
.metric strong { font:600 24px/1.15 -apple-system,BlinkMacSystemFont,"SF Pro Display",sans-serif; letter-spacing:-.3px; overflow-wrap:anywhere; text-transform:capitalize }
.metric.hero { grid-column:span 2; display:flex; flex-direction:column; justify-content:space-between }
.metric.hero strong { font-size:40px; letter-spacing:-1px }
.metric.hero strong[data-state="occupied"] { color:var(--accent) }
.metric.plate strong { font-family:ui-monospace,"SF Mono",Menlo,monospace; text-transform:none; letter-spacing:.5px }
.panel { overflow:hidden }
.toolbar {display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; padding:16px 20px; border-bottom:1px solid var(--border)}
.toolbar h2 {margin:0; font-size:17px; font-weight:600; letter-spacing:-.2px} .actions { display:flex; flex-wrap:wrap; align-items:center; gap:10px }
#garage {margin-bottom:20px}
#garage-form {padding:18px 20px 20px; display:grid; gap:16px}
#garage-form[hidden] {display:none}
#garage-form label { display:grid; gap:6px; min-width:min(100%,240px); color:var(--muted); font-size:12px; font-weight:500; letter-spacing:.06em; text-transform:uppercase }
#garage-form input {font:500 16px/1.2 -apple-system,BlinkMacSystemFont,sans-serif; color:var(--text); background:#0f1216; padding:11px 13px;
 border:1px solid var(--border); border-radius:10px; outline:none; text-transform:none; letter-spacing:0; transition:border-color .15s, box-shadow .15s}
#garage-key { font-family:ui-monospace,"SF Mono",Menlo,monospace !important; letter-spacing:.08em !important }
#garage-form input:focus {border-color:rgba(95,224,196,.6); box-shadow:0 0 0 4px rgba(95,224,196,.14)}
#garage-result { margin:0; min-height:1.5em; color:var(--text); font-weight:500 }
#garage-result:not(:empty)::before { content:""; display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--accent); margin-right:9px; vertical-align:2px }
button {font:500 14px/1 -apple-system,BlinkMacSystemFont,sans-serif; color:var(--text); background:rgba(255,255,255,.06); border:1px solid var(--border);
 border-radius:999px; padding:9px 16px; cursor:pointer; transition:background .15s}
button:hover {background:rgba(255,255,255,.12)}
button[value="check"] {background:var(--accent); color:#06231d; border-color:transparent; font-weight:600}
button[value="check"]:hover {background:#7ce9d1}
button:disabled {opacity:.5; cursor:default}
.switch {cursor:pointer; color:var(--muted); font-size:13px}
.toolbar a { color:var(--muted); font-size:13px; text-decoration:none } .toolbar a:hover { color:var(--text) }
pre {font:12.5px/1.75 ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace; margin:0; white-space:pre-wrap; overflow-wrap:anywhere;
 padding:14px 20px; min-height:280px; max-height:58vh; overflow:auto; color:#d4dbe2}
pre .ts {color:#5d6873} pre .lvl {display:inline-block; width:5.5em; color:var(--accent)} pre .lvl.WARNING {color:var(--warn)} pre .lvl.ERROR {color:var(--err)}
pre .WARNING-line .msg {color:#ffe2ad}
footer {margin-top:16px; color:#6b7580; font-size:12px}
@media(max-width:760px) {.grid {grid-template-columns:1fr 1fr} .metric.hero strong {font-size:32px} .metric strong {font-size:20px} h1 {font-size:26px}}
</style></head><body><main>
<header><div><h1>Park<b>Sight</b></h1><small>UNO Q · Local monitoring, no internet required</small></div><span id="connection" class="pill">Connecting…</span></header>
<section class="grid" aria-label="Live status">
<div class="metric hero"><span>Parking stall</span><strong id="stall">—</strong></div>
<div class="metric"><span>Camera</span><strong id="camera">—</strong></div>
<div class="metric plate"><span>Last plate</span><strong id="plate">—</strong></div>
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
 function render() {
  if (!lines.length) { log.textContent = 'No logs yet'; }
  else log.replaceChildren(...lines.map(text => {
   const m = /^(\[[^\]]*\]) (\S+)\s+([\s\S]*)$/.exec(text); const row = document.createElement('div');
   if (!m) { row.textContent = text; return row; }
   row.className = m[2] + '-line';
   for (const [cls, value] of [['ts', m[1] + ' '], ['lvl ' + m[2], m[2]], ['msg', m[3]]]) {
    const span = document.createElement('span'); span.className = cls; span.textContent = value; row.append(span);
   }
   return row;
  }));
  if ($('autoscroll').checked) log.scrollTop=log.scrollHeight;
 }
 function seconds(s) {s=Math.floor(s||0); return `${Math.floor(s/3600)}h ${fmt(Math.floor(s%3600/60))}m ${fmt(s%60)}s`;}
 async function poll(){
  try {
   const res=await fetch('/api/logs?after='+encodeURIComponent(last),{cache:'no-store'});
   if(!res.ok) throw new Error('HTTP '+res.status);
   const data=await res.json();
   if(data.reset || (data.last_id < last)){ last=0; lines=[]; }
   for(const e of data.entries){ last=Math.max(last,e.id); lines.push(`[${formatTime(e.time)}] ${e.level.padEnd(7)} ${e.message}`); }
   if(lines.length>600) lines=lines.slice(-600);
   render(); $('stall').textContent=data.status.stall; $('stall').dataset.state=data.status.stall; $('camera').textContent=data.status.camera;
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
   $('connection').textContent='Live · Connected'; $('connection').classList.remove('down'); connected=true;
  }catch(e){$('connection').textContent='Disconnected';$('connection').classList.add('down');connected=false; }
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
