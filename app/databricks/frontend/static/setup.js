"use strict";
const $ = (id) => document.getElementById(id);
const root = "/api/camera-setup";
const hints = {
  divider: "Drag from one end of the divider to the other. The arrow shows entry direction.",
  entry: "Drag a box around the area where incoming plates should be visible.",
  exit: "Drag a box around the area where outgoing plates should be visible."
};
const tools = [...$("tools").querySelectorAll("button")];
let active = "divider";
let snapshot = null;
let drawing = null;
let layout = {};
let busy = false;
let ready = false;
const toSvg = (value) => value * 1000;
const pause = (ms) => new Promise(resolve => setTimeout(resolve, ms));

function message(text) {
  $("status").textContent = text;
}

async function request(path = "", options = {}) {
  const response = await fetch(root + path, {cache: "no-store", ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Check the layout and try again.");
  return data;
}

function attrs(node, values) {
  for (const [name, value] of Object.entries(values)) node.setAttribute(name, toSvg(value));
}

function render() {
  for (const name of ["entry", "exit"]) {
    const zone = layout[name];
    const element = $(name + "Shape");
    element.toggleAttribute("hidden", !zone);
    if (zone) attrs(element, zone);
  }
  $("dividerShape").toggleAttribute("hidden", !layout.divider);
  $("directionShape").toggleAttribute("hidden", !layout.divider);
  if (layout.divider) {
    const [a, b] = layout.divider;
    attrs($("dividerShape"), {x1:a.x, y1:a.y, x2:b.x, y2:b.y});
    const dx = (b.x - a.x) * snapshot.width;
    const dy = (b.y - a.y) * snapshot.height;
    const length = Math.hypot(dx, dy);
    if (length > 0) {
      const sign = layout.reverse ? -1 : 1;
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      const half = Math.min(snapshot.width, snapshot.height) * 0.045;
      const x = sign * -dy / length * half / snapshot.width;
      const y = sign * dx / length * half / snapshot.height;
      attrs($("directionShape"), {x1:mx-x, y1:my-y, x2:mx+x, y2:my+y});
    }
  }
  $("capture").disabled = busy;
  $("save").disabled = busy || !ready || !layout.divider || !layout.entry || !layout.exit;
  $("reset").disabled = busy || !ready;
  $("reverse").disabled = busy || !ready || !layout.divider;
}

function openSnapshot(state) {
  snapshot = state.snapshot;
  layout = state.calibration ? {
    divider:state.calibration.divider, entry:state.calibration.entry,
    exit:state.calibration.exit, reverse:state.calibration.reverse
  } : {};
  ready = false;
  $("preview").hidden = true;
  $("empty").hidden = false;
  $("resolution").textContent = snapshot ? `${snapshot.width} × ${snapshot.height}` : "No image";
  if (snapshot) {
    $("reference").width = snapshot.width;
    $("reference").height = snapshot.height;
    $("reference").src = root + "/snapshot/" + snapshot.id;
  }
  render();
}

$("reference").onload = () => {
  ready = true;
  $("preview").hidden = false;
  $("empty").hidden = true;
  render();
};
$("reference").onerror = () => message("The reference image could not be loaded. Capture it again.");

function point(event) {
  const rect = $("overlay").getBoundingClientRect();
  const clamp = value => Math.max(0, Math.min(1, value));
  return {x:clamp((event.clientX - rect.left) / rect.width), y:clamp((event.clientY - rect.top) / rect.height)};
}
function shape(a, b) {
  if (active === "divider") return [a,b];
  return {x:Math.min(a.x,b.x), y:Math.min(a.y,b.y), width:Math.abs(a.x-b.x), height:Math.abs(a.y-b.y)};
}

const overlay = $("overlay");
overlay.onpointerdown = event => {
  if (busy || !ready || drawing || event.button !== 0) return;
  drawing = {pointer:event.pointerId, start:point(event), previous:layout[active]};
  overlay.setPointerCapture(event.pointerId);
};
overlay.onpointermove = event => {
  if (!drawing || drawing.pointer !== event.pointerId) return;
  layout[active] = shape(drawing.start, point(event));
  render();
};
overlay.onpointerup = overlay.onpointercancel = event => {
  if (!drawing || drawing.pointer !== event.pointerId) return;
  const end = point(event);
  const dx = Math.abs(end.x - drawing.start.x);
  const dy = Math.abs(end.y - drawing.start.y);
  const valid = active === "divider" ? Math.hypot(dx, dy) >= .02 : dx >= .02 && dy >= .02;
  layout[active] = event.type === "pointerup" && valid ? shape(drawing.start,end) : drawing.previous;
  drawing = null;
  render();
};
overlay.onkeydown = event => {
  const direction = {ArrowLeft:[-1,0], ArrowRight:[1,0], ArrowUp:[0,-1], ArrowDown:[0,1]}[event.key];
  const current = layout[active];
  if (!direction || !current || busy || !ready || drawing) return;
  event.preventDefault();
  const step = event.shiftKey ? .02 : .005;
  const bounds = active === "divider" ? current : [
    {x:current.x, y:current.y},
    {x:current.x + current.width, y:current.y + current.height}
  ];
  const shift = (axis, delta) => Math.max(
    -Math.min(...bounds.map(point => point[axis])),
    Math.min(1 - Math.max(...bounds.map(point => point[axis])), delta)
  );
  const x = shift("x", direction[0] * step);
  const y = shift("y", direction[1] * step);
  layout[active] = active === "divider" ? current.map(point => ({x:point.x + x, y:point.y + y})) :
    {...current, x:current.x + x, y:current.y + y};
  render();
};

for (const button of tools) {
  button.onclick = () => {
    if (drawing) return;
    active = button.dataset.tool;
    for (const other of tools) other.setAttribute("aria-pressed", String(button === other));
    $("hint").textContent = hints[active];
  };
}
$("reverse").onclick = () => { layout.reverse = !layout.reverse; render(); };
$("reset").onclick = () => { layout = {}; message("Drawing cleared. Save a new layout to replace the stored one."); render(); };

$("capture").onclick = async () => {
  if (drawing) return;
  busy = true;
  render();
  message("Waiting for a frame from the installed camera…");
  try {
    const result = await request("/capture", {method:"POST", headers:{"X-ParkSight-Setup":"1"}});
    for (let attempt = 0; attempt < 30; attempt++) {
      await pause(1000);
      const state = await request();
      if (state.snapshot?.id === result.id) {
        openSnapshot(state);
        message("Reference captured. Check the divider and zones before saving.");
        return;
      }
      if (state.pending !== result.id) break;
    }
    message("The camera did not return a frame. Check that the UNO Q and webcam are online, then retry.");
  } catch (error) {
    message(error.message);
  } finally {
    busy = false;
    render();
  }
};

$("save").onclick = async () => {
  if (drawing) return;
  busy = true;
  render();
  try {
    await request("/calibration", {
      method:"PUT", headers:{"Content-Type":"application/json", "X-ParkSight-Setup":"1"},
      body:JSON.stringify({
        reference_id:snapshot.id, divider:layout.divider, entry:layout.entry, exit:layout.exit,
        reverse:!!layout.reverse
      })
    });
    message("Layout saved.");
  } catch (error) {
    message(error.message);
  } finally {
    busy = false;
    render();
  }
};

request().then(state => {
  openSnapshot(state);
  message(state.calibration ? "Saved layout loaded." : state.snapshot ? "Draw the divider and both zones." : "");
}).catch(error => message(error.message));
