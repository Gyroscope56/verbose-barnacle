(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const root = "/api/camera-setup/stall";
  const errors = {
    insufficient: "Not enough valid readings. Check that the sensor is connected and the target is within 1.2 m.",
    unstable: "The distance changed during sampling. Hold the target still and sample again.",
    timeout: "No sample arrived. Check that the UNO Q and distance sensor are online."
  };
  let state;
  let busy = false;
  let timer;
  let until = Date.now() + 30000;

  async function request(path = "", method = "GET", body) {
    const options = method === "GET" ? {} : {
      method,
      headers: {"X-ParkSight-Setup": "1", ...(body ? {"Content-Type": "application/json"} : {})},
      ...(body ? {body: JSON.stringify(body)} : {})
    };
    const response = await fetch(root + path, {cache: "no-store", ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Sensor setup unavailable.");
    return data;
  }

  function controls() {
    const disabled = !state || busy || !!state.pending;
    for (const kind of ["clear", "occupied"]) el("stall-" + kind).disabled = disabled;
    el("stall-apply").disabled = disabled || state.clear_mm === null || state.occupied_mm === null;
    const spot = el("stall-spot");
    spot.disabled = !state || busy || spot.options.length < 2;
    el("stall-assign").disabled = spot.disabled || !spot.value || spot.value === state.spot_id;
  }

  function occupancy() {
    if (!state.spot_id) return "No spot linked. The sensor won’t update the garage table.";
    if (!state.applied) return `Linked to ${state.spot_id}. Apply a calibration to start updating it.`;
    if (!state.occupancy_fresh) return `Linked to ${state.spot_id}. Waiting for a reading from the UNO Q…`;
    return `${state.spot_id} is ${state.is_occupied ? "occupied" : "free"} · updated ${new Date(state.occupancy_reported_at).toLocaleTimeString()}`;
  }

  async function loadSpots() {
    const spot = el("stall-spot");
    try {
      const {spots} = await request("/spots");
      spot.replaceChildren(new Option(spots.length ? "Choose a spot" : "No spots in the garage table", ""),
        ...spots.map(id => new Option(id, id)));
      if (state && state.spot_id) spot.value = state.spot_id;
    } catch (error) {
      el("stall-occupancy").textContent = error.message;
    }
    controls();
  }

  function render() {
    for (const kind of ["clear", "occupied"]) {
      const value = state[kind + "_mm"];
      el("stall-" + kind + "-value").textContent = value === null ? "No sample" : value + " mm";
    }
    const settings = state.settings;
    el("stall-thresholds").textContent = settings
      ? `Occupied below ${settings.occupied_below_mm} mm · Clear above ${settings.clear_above_mm} mm`
      : "Using the board’s default thresholds.";
    el("stall-status").textContent = state.pending ? "Sampling distance. Keep the target still…"
      : errors[state.error] || (state.applied ? "Calibration active on the UNO Q."
        : settings ? "Calibration saved. Waiting for the UNO Q to apply it." : "");
    el("stall-occupancy").textContent = occupancy();
    const spot = el("stall-spot");
    if (document.activeElement !== spot && state.spot_id) spot.value = state.spot_id;
    controls();
  }

  async function refresh() {
    clearTimeout(timer);
    try {
      state = await request();
      render();
      if (state.pending || (state.settings && !state.applied && Date.now() < until)) {
        timer = setTimeout(refresh, 1000);
      } else if (state.spot_id) {
        timer = setTimeout(refresh, 5000);
      }
    } catch (error) {
      el("stall-status").textContent = error.message;
    }
  }

  async function act(path, method = "POST", body) {
    busy = true;
    controls();
    try {
      await request(path, method, body);
      until = Date.now() + 30000;
      await refresh();
    } catch (error) {
      el("stall-status").textContent = error.message;
    } finally {
      busy = false;
      controls();
    }
  }

  el("stall-clear").onclick = () => act("/sample/clear");
  el("stall-occupied").onclick = () => act("/sample/occupied");
  el("stall-apply").onclick = () => act("/apply");
  el("stall-spot").onchange = controls;
  el("stall-assign").onclick = () => act("/spot", "PUT", {spot_id: el("stall-spot").value});
  refresh().then(loadSpots);
})();
