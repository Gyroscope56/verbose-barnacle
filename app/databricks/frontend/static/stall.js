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

  async function request(path = "", post = false) {
    const options = post ? {method: "POST", headers: {"X-ParkSight-Setup": "1"}} : {};
    const response = await fetch(root + path, {cache: "no-store", ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Sensor setup unavailable.");
    return data;
  }

  function controls() {
    const disabled = !state || busy || !!state.pending;
    for (const kind of ["clear", "occupied"]) el("stall-" + kind).disabled = disabled;
    el("stall-apply").disabled = disabled || state.clear_mm === null || state.occupied_mm === null;
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
    controls();
  }

  async function refresh() {
    clearTimeout(timer);
    try {
      state = await request();
      render();
      if (state.pending || (state.settings && !state.applied && Date.now() < until)) {
        timer = setTimeout(refresh, 1000);
      }
    } catch (error) {
      el("stall-status").textContent = error.message;
    }
  }

  async function act(path) {
    busy = true;
    controls();
    try {
      await request(path, true);
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
  refresh();
})();
