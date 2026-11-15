"use strict";

const el = id => document.getElementById(id);
const jpeg = data => "data:image/jpeg;base64," + data;
let paused = false;
let timer;
let pending = false;
let lastPreview;
let lastReport;
let zones;
let zoneSize;
let demo = false;
let startingManual = false;
let manualId;
let manualPinned = false;

async function load(path, options) {
  const response = await fetch("/api/debug/" + path, {cache: "no-store", ...options});
  const content = await response.json();
  if (!response.ok) throw new Error(content.detail || "Debug feed unavailable");
  return content;
}

function renderZones() {
  const frame = el("live-frame");
  const [width, height] = zoneSize || [];
  const compatible = width && Math.abs(frame.naturalWidth / frame.naturalHeight - width / height) < .01;
  el("zones").toggleAttribute("hidden", !compatible || !zones || frame.hidden);
  if (!compatible || !zones) return;
  for (const name of ["entry", "exit"]) {
    for (const [attribute, value] of Object.entries(zones[name])) {
      el(name + "-box").setAttribute(attribute, value * 1000);
    }
  }
}

el("live-frame").addEventListener("load", () => {
  const image = el("live-frame");
  el("live-view").style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
  renderZones();
});

function renderPreview(state) {
  zones = state.zones;
  zoneSize = state.zone_image_size;
  if (state.preview && state.preview_at !== lastPreview) {
    el("live-frame").src = jpeg(state.preview);
    lastPreview = state.preview_at;
  }
  el("live-frame").hidden = !state.preview;
  el("live-empty").hidden = !!state.preview;
  el("live-status").textContent = state.preview ? "Live" : "Waiting for camera";
  renderZones();
}

function renderReport(report, receivedAt, manual = false) {
  if (!report) return;
  el("inference").hidden = false;
  el("decision").textContent = report.decision;
  const meta = [manual ? "Manual run" : null, new Date(receivedAt).toLocaleTimeString(), `Frame ${report.frame_number}`,
    report.zone, `${report.elapsed.toFixed(2)} s`, `Threshold ${report.threshold.toFixed(2)}`];
  if (report.detection) meta.push(`Score ${report.detection.score.toFixed(3)}`);
  el("inference-meta").textContent = meta.filter(Boolean).join(" · ");
  el("evaluated").src = jpeg(report.frame);
  const overlay = el("detection");
  overlay.toggleAttribute("hidden", !report.detection);
  if (report.detection) {
    overlay.setAttribute("viewBox", `0 0 ${report.width} ${report.height}`);
    report.detection.box.forEach((value, i) => {
      overlay.firstElementChild.setAttribute(["x", "y", "width", "height"][i], value);
    });
  }
  for (const [imageId, emptyId, image] of [
    ["plate-crop", "crop-empty", report.crop], ["ocr-input", "ocr-empty", report.ocr_input]
  ]) {
    el(imageId).hidden = !image;
    el(emptyId).hidden = !!image;
    if (image) el(imageId).src = jpeg(image);
  }
  el("notes").replaceChildren(...report.notes.map(note => {
    const item = document.createElement("li");
    item.textContent = note;
    return item;
  }));
}

const outcomes = {inside: "Checked in", exited: "Visit closed", unbooked: "No booking",
  ambiguous: "Multiple plate matches", already_inside: "Already inside",
  denied: "Entry denied", not_inside: "No active visit"};

function manualControls() {
  const busy = startingManual || !!manualId;
  el("demo-toggle").disabled = busy;
  el("demo-toggle").setAttribute("aria-pressed", demo);
  el("manual-run").hidden = !demo;
  el("manual-run").disabled = paused || busy;
  el("toggle").disabled = busy;
  el("manual-status").hidden = !demo;
}

async function pollManual() {
  try {
    const {report, received_at} = await load("run/" + manualId);
    if (!report) return;
    renderReport(report, received_at, true);
    manualPinned = true;
    el("manual-status").textContent = "Manual run complete.";
  } catch (error) {
    el("manual-status").textContent = error.message;
  }
  manualId = null;
  manualControls();
}

async function poll() {
  if (paused || document.hidden || pending) return;
  pending = true;
  let delay = 500;
  try {
    const state = await load("view", {method: "POST", headers: {"X-ParkSight-Setup": "1"}});
    if (paused || document.hidden) return;
    renderPreview(state);
    if (state.garage) {
      const {zone, plate, outcome, received_at} = state.garage;
      el("garage-result").textContent =
        `${plate} · ${zone} · ${outcomes[outcome] || outcome} · ${new Date(received_at).toLocaleTimeString()}`;
    }
    if (manualId) await pollManual();
    if (!manualPinned && !manualId && state.report_id && state.report_id !== lastReport) {
      const {report, received_at} = await load("report");
      renderReport(report, received_at);
      lastReport = report?.id;
    }
  } catch (error) {
    el("live-status").textContent = error.message;
    delay = 2000;
  } finally {
    pending = false;
    if (!paused && !document.hidden) timer = setTimeout(poll, delay);
  }
}

el("toggle").addEventListener("click", () => {
  paused = !paused;
  clearTimeout(timer);
  el("toggle").textContent = paused ? "Resume preview" : "Pause preview";
  manualControls();
  if (paused) el("live-status").textContent = "Paused";
  else poll();
});
el("demo-toggle").addEventListener("click", () => {
  demo = !demo;
  if (!demo && manualPinned) {
    manualPinned = false;
    lastReport = null;
    el("inference").hidden = true;
    el("decision").textContent = "Waiting for a motion-triggered read.";
    el("inference-meta").textContent = "";
  }
  el("manual-status").textContent = "";
  manualControls();
});
el("manual-run").addEventListener("click", async () => {
  startingManual = true;
  manualControls();
  el("manual-status").textContent = "Waiting for a fresh burst from the UNO Q…";
  try {
    const result = await load("run", {method: "POST", headers: {"X-ParkSight-Setup": "1"}});
    manualId = result.id;
  } catch (error) {
    el("manual-status").textContent = error.message;
  } finally {
    startingManual = false;
    manualControls();
  }
});
document.addEventListener("visibilitychange", () => {
  clearTimeout(timer);
  if (!document.hidden) poll();
});
manualControls();
poll();
