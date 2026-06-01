// HaphazardNet panel — polls the API and paints the dashboard.
const $ = (id) => document.getElementById(id);
const STATUS_MS = 3000;
const CLIENTS_MS = 4000;

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

// ---------- MODE ----------
let modeState = null;

function renderModes(state) {
  modeState = state;
  const wrap = $("modes");
  const cur = state.current, req = state.requested;
  wrap.innerHTML = "";
  for (const id of Object.keys(state.modes)) {
    const m = state.modes[id];
    const btn = document.createElement("button");
    btn.className = "mode-btn"
      + (id === cur ? " active" : "")
      + (req && req === id && req !== cur ? " pending" : "");
    btn.innerHTML = `<span class="mb-label">${m.label}</span>`
      + `<span class="mb-tag">${m.tagline}</span>`;
    btn.onclick = () => setMode(id, m.label);
    wrap.appendChild(btn);
  }
  const note = $("mode-note");
  if (req && req !== cur) note.textContent = `Switching to ${state.modes[req].label}… applying.`;
  else note.textContent = `Active: ${state.modes[cur] ? state.modes[cur].label : cur}`;
}

async function setMode(id, label) {
  if (modeState && modeState.current === id) return;
  if (!confirm(`Switch to ${label} mode?`)) return;
  $("mode-note").textContent = `Requesting ${label}…`;
  try {
    renderModes(await getJSON("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: id }),
    }));
  } catch (e) {
    $("mode-note").textContent = "Mode change failed.";
  }
}

// ---------- BATTERY ----------
function paintBattery(b) {
  const pct = b.percent;
  const fill = $("batt-fill");
  if (pct == null) { $("batt-pct").textContent = "--"; return; }
  fill.style.width = Math.max(4, pct) + "%";
  fill.style.background = pct < 15 ? "var(--red)" : pct < 35 ? "var(--amber)" : "var(--lime)";
  fill.style.boxShadow = "0 0 8px " + (pct < 15 ? "var(--red)" : pct < 35 ? "var(--amber)" : "var(--lime)");
  $("batt-pct").textContent = Math.round(pct) + "%" + (b.charging ? " ⚡" : "");

  $("p-pct").textContent = Math.round(pct) + "%" + (b.mock ? " (sim)" : "");
  $("p-state").textContent = b.charging ? "Charging ⚡" : "On battery";
  $("p-state").className = "v " + (b.charging ? "ok" : pct < 20 ? "bad" : "");
  $("p-volt").textContent = b.voltage != null ? b.voltage.toFixed(2) + " V" : "--";
  $("p-draw").textContent = b.current_ma != null ? Math.abs(Math.round(b.current_ma)) + " mA" : "--";
  $("p-pwr").textContent = b.power_w != null ? b.power_w.toFixed(2) + " W" : "--";
  $("p-rt").textContent = b.charging ? "—" :
    (b.runtime_min != null ? Math.floor(b.runtime_min / 60) + "h" + (b.runtime_min % 60) + "m" : "--");
}

// ---------- SYSTEM ----------
function svc(v) { return v === true ? ["RUNNING", "ok"] : v === false ? ["STOPPED", "bad"] : ["n/a", "muted"]; }
function paintSystem(sys) {
  const s = sys.services || {};
  let [t, c] = svc(s.taky); $("s-taky").textContent = t; $("s-taky").className = "v " + c;
  const apUp = s.hostapd === true && s.dnsmasq === true;
  $("s-ap").textContent = apUp ? "UP" : (s.hostapd == null ? "n/a" : "DOWN");
  $("s-ap").className = "v " + (apUp ? "ok" : s.hostapd == null ? "muted" : "bad");
  const tmp = sys.cpu_temp_c;
  $("s-temp").textContent = tmp != null ? tmp + "°C" : "--";
  $("s-temp").className = "v " + (tmp == null ? "" : tmp > 75 ? "bad" : tmp > 65 ? "warn" : "");
  $("s-mem").textContent = sys.mem_percent != null ? sys.mem_percent + "%" : "--";
  $("s-up").textContent = sys.uptime || "--";
  $("s-load").textContent = sys.load != null ? sys.load.toFixed(2) : "--";
}

// ---------- CLIENTS ----------
function paintClients(data) {
  $("net-count").textContent = data.counts.tak_connected;
  const tbody = $("users");
  if (!data.clients.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="muted">no devices on the net</td></tr>`;
    return;
  }
  tbody.innerHTML = data.clients.map((u) => {
    const cs = u.callsign
      ? `<span class="cs">${u.callsign}</span>${u.is_sdr ? '<span class="tag-sdr">SDR</span>' : ""}`
      : `<span class="muted">—</span>${u.is_sdr ? '<span class="tag-sdr">SDR</span>' : ""}`;
    const tak = u.is_sdr ? '<span class="muted">feed</span>'
      : `<span class="dot ${u.tak_connected ? "on" : "off"}"></span>`;
    return `<tr><td>${cs}</td><td>${u.hostname || "<span class='muted'>?</span>"}</td>`
      + `<td>${u.ip}</td><td>${tak}</td></tr>`;
  }).join("");
}

// ---------- LOOPS ----------
async function tickStatus() {
  try {
    const d = await getJSON("/api/status");
    renderModes(d.mode);
    paintBattery(d.battery);
    paintSystem(d.system);
  } catch (e) { /* keep last paint */ }
}
async function tickClients() {
  try { paintClients(await getJSON("/api/clients")); } catch (e) {}
}
function tickClock() {
  $("clock").textContent = new Date().toISOString().substr(11, 5);
}

tickStatus(); tickClients(); tickClock();
setInterval(tickStatus, STATUS_MS);
setInterval(tickClients, CLIENTS_MS);
setInterval(tickClock, 1000);

// ---------- POWER: tap to arm, slide to confirm (shutdown + reboot) ----------
function slideConfirm(p, endpoint) {
  const open = $(p + "-open"), confirm = $(p + "-confirm"), done = $(p + "-done");
  const track = $(p + "-track"), knob = $(p + "-knob"), fill = $(p + "-fill"), hint = $(p + "-hint");
  if (!open) return;
  let dragging = false, startX = 0, x = 0, maxX = 0;

  function reset() { x = 0; knob.style.left = "3px"; fill.style.width = "0"; hint.style.opacity = "1"; }
  open.onclick = () => { open.hidden = true; confirm.hidden = false; reset(); };
  $(p + "-cancel").onclick = () => { confirm.hidden = true; open.hidden = false; };

  knob.addEventListener("pointerdown", (e) => {
    dragging = true; startX = e.clientX - x;
    maxX = track.offsetWidth - knob.offsetWidth - 6;
    try { knob.setPointerCapture(e.pointerId); } catch (_) {}
  });
  document.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    x = Math.max(0, Math.min(maxX, e.clientX - startX));
    knob.style.left = (3 + x) + "px";
    fill.style.width = (x + knob.offsetWidth) + "px";
    hint.style.opacity = String(Math.max(0, 1 - x / maxX));
  });
  document.addEventListener("pointerup", () => {
    if (!dragging) return; dragging = false;
    if (maxX > 0 && x >= maxX * 0.92) fire(); else reset();
  });

  async function fire() {
    confirm.hidden = true; done.hidden = false;
    try {
      await fetch(endpoint, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: "{}" });
    } catch (_) { /* connection drops as it powers down/reboots — expected */ }
  }
}
slideConfirm("rb", "/api/reboot");
slideConfirm("sd", "/api/shutdown");
