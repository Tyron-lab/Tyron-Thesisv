/* =============================================
   SENSOR DASHBOARD – FRONTEND LOGIC (FULL)
   - Shows values for ALL sensors
   - Adds toggleRelay() / toggleServo()
   - ✅ MIC now uses VOSK + LIVE WAVE (no clap)
   - Uses:
        GET  /api/sensors      (main polling)
        GET  /api/mic_wave     (fast wave + text)
        POST /api/mic_command  (clear command, optional)
============================================= */

const qs  = (sel, root = document) => root.querySelector(sel);
const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

async function safeJson(res) {
  try { return await res.json(); } catch { return null; }
}

function setSmall(cardId, text) {
  const card = document.getElementById(cardId);
  if (!card) return;
  const el = card.querySelector(".last-update");
  if (!el) return;
  el.textContent = text ?? "";
}

function setCardText(cardId, text, isError=false) {
  const card = document.getElementById(cardId);
  if (!card) return;
  const el = card.querySelector(".sensor-value");
  if (!el) return;
  el.textContent = text ?? "—";
  el.style.opacity = "1";
  el.style.color = isError ? "#ef4444" : "";
}

async function postJSON(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await safeJson(res);
  return { ok: res.ok, data };
}

// -------------------------
// Sensor card toggles
// -------------------------
qsa(".sensor-card:not(.disabled)").forEach(card => {
  const id = card.id;

  // Exclude relay/servo (they use inline onclick)
  if (id === "Relay" || id === "servomotor") return;

  // Exclude tools (they use buttons)
  if (id === "BUZZER" || id === "LCD_TOOL") return;

  card.addEventListener("click", async () => {
    const r = await postJSON("/api/toggle", { sensor: id });

    if (!r.ok || r.data?.ok === false) {
      const msg = r.data?.error || "Toggle failed";
      setCardText(id, `Error: ${msg}`, true);
      return;
    }

    // show backend-side init errors immediately if any
    if (r.data?.error) setCardText(id, `Error: ${r.data.error}`, true);
  });
});

// -------------------------
// Relay + Servo
// -------------------------
async function toggleRelay() {
  const r = await postJSON("/api/toggle", { sensor: "Relay" });
  if (!r.ok || r.data?.ok === false) {
    setCardText("Relay", `Error: ${r.data?.error || "Relay toggle failed"}`, true);
  }
}

async function toggleServo() {
  const r = await postJSON("/api/toggle", { sensor: "servomotor" });
  if (!r.ok || r.data?.ok === false) {
    setCardText("servomotor", `Error: ${r.data?.error || "Servo toggle failed"}`, true);
  }
}

window.toggleRelay = toggleRelay;
window.toggleServo = toggleServo;

// -------------------------
// Tool controls
// -------------------------
function buzzerToggle() {
  postJSON("/api/buzzer", { mode: "toggle" })
    .then(r => {
      if (!r.ok || r.data?.ok === false) {
        setCardText("BUZZER", `Error: ${r.data?.error || "Buzzer failed"}`, true);
        return;
      }
      updateBuzzerStatus({ on: !!r.data?.on });
    })
    .catch(e => setCardText("BUZZER", `Error: ${String(e)}`, true));
}

function buzzerBeep() {
  postJSON("/api/buzzer", { mode: "beep", count: 2, on_ms: 140, off_ms: 140 })
    .then(r => {
      if (!r.ok || r.data?.ok === false) {
        setCardText("BUZZER", `Error: ${r.data?.error || "Beep failed"}`, true);
        return;
      }
      updateBuzzerStatus({ on: false });
    })
    .catch(e => setCardText("BUZZER", `Error: ${String(e)}`, true));
}

function lcdSend() {
  const line1 = (qs("#lcd-line1")?.value || "").trim();
  const line2 = (qs("#lcd-line2")?.value || "").trim();

  postJSON("/api/lcd", { line1, line2 })
    .then(r => {
      if (!r.ok || r.data?.ok === false) {
        setCardText("LCD_TOOL", `Error: ${r.data?.error || "LCD failed"}`, true);
        return;
      }
      updateLcdStatus({ line1, line2 });
    })
    .catch(e => setCardText("LCD_TOOL", `Error: ${String(e)}`, true));
}

function lcdClear() {
  postJSON("/api/lcd", { clear: true })
    .then(r => {
      if (!r.ok || r.data?.ok === false) {
        setCardText("LCD_TOOL", `Error: ${r.data?.error || "LCD clear failed"}`, true);
        return;
      }
      updateLcdStatus({ line1: "", line2: "" });
    })
    .catch(e => setCardText("LCD_TOOL", `Error: ${String(e)}`, true));
}

window.buzzerToggle = buzzerToggle;
window.buzzerBeep = buzzerBeep;
window.lcdSend = lcdSend;
window.lcdClear = lcdClear;

// -------------------------
// Status UI helpers
// -------------------------
function updateBuzzerStatus(buz) {
  const el = qs("#buzzer-status");
  if (!el) return;
  el.textContent = buz.on ? "ON" : "OFF";
  el.style.color = buz.on ? "#22c55e" : "#ef4444";
}

function updateLcdStatus(lcd) {
  const el = qs("#lcd-status");
  if (!el) return;
  const l1 = (lcd.line1 || "").slice(0, 16);
  const l2 = (lcd.line2 || "").slice(0, 16);
  el.textContent = (l1 || l2) ? `${l1} | ${l2}` : "—";
}

// -------------------------
// Format ALL sensors
// -------------------------
function formatSensorValue(name, data) {
  if (!data) return "—";
  if (data.error) return `Error: ${data.error}`;

  if (name === "DHT11") {
    const t = data.temperature;
    const h = data.humidity;
    if (t == null || h == null) return "Reading...";
    return `${t} °C • ${h}%`;
  }

  // ✅ MIC: voice + audio level (no clap)
  if (name === "MIC") {
    const peak = data.peak;
    const rms  = data.rms;
    const p = (peak == null) ? "—" : Number(peak).toFixed(3);
    const r = (rms  == null) ? "—" : Number(rms).toFixed(3);

    const text = (data.text || "").trim();
    const partial = (data.partial || "").trim();
    const cmd = (data.command || "").trim();

    const speechLine = cmd
      ? `CMD: ${cmd}`
      : (text ? `Text: ${text}` : (partial ? `... ${partial}` : "Say: open / hello"));

    return `Peak: ${p} • RMS: ${r} • ${speechLine}`;
  }

  if (name === "MHMQ") {
    const lvl = (data.level_percent != null) ? `${data.level_percent}%` : "—";
    return data.gas_detected ? `Gas Detected! (${lvl})` : `Clear (${lvl})`;
  }

  if (name === "PIR") {
    return data.motion ? `MOTION! (${data.count ?? 0})` : `No motion (${data.count ?? 0})`;
  }

  if (name === "ULTRASONIC") {
    if (data.distance_cm == null) return "Reading...";
    return `${data.distance_cm} cm`;
  }

  if (name === "BMP280") {
    if (data.temperature == null || data.pressure == null) return "Reading...";
    return `${data.temperature} °C • ${data.pressure} hPa • ${data.altitude ?? "—"} m`;
  }

  if (name === "MPU6050") {
    if (data.ax == null) return "Reading...";
    const f = (v) => (typeof v === "number" ? v.toFixed(2) : v);
    return `A:${f(data.ax)},${f(data.ay)},${f(data.az)} • G:${f(data.gx)},${f(data.gy)},${f(data.gz)}`;
  }

  return "—";
}

// -------------------------
// MAIN Polling (ALL sensors)
// -------------------------
async function updateDashboard() {
  const res = await fetch("/api/sensors", { cache: "no-store" });
  const state = await safeJson(res);
  if (!res.ok || !state) return;

  const data = state.data || {};

  qsa(".sensor-card").forEach(card => {
    const name = card.id;

    const isTool = (name === "BUZZER" || name === "LCD_TOOL");
    if (isTool) return;

    const active = !!state[name];
    card.classList.toggle("active", active);

    if (name === "Relay") {
      const d = data.Relay || {};
      const anyOn = !!(d.ch1 || d.ch2 || d.ch3 || d.ch4);
      const el = qs("#relay-status");
      if (el) {
        el.textContent = anyOn ? "ON" : "OFF";
        el.style.color = anyOn ? "#22c55e" : "#ef4444";
      }
      return;
    }

    if (name === "servomotor") {
      const d = data.servomotor || {};
      const el = qs("#servo-status");
      if (el) {
        const on = active;
        el.textContent = on ? `ON – ${d.angle ?? 90}°` : "OFF";
        el.style.color = on ? "#22c55e" : "#ef4444";
      }
      return;
    }

    // MIC card has special UI (wave + mic-line), but keep fallback too
    if (name === "MIC") {
      const micLine = qs("#mic-line");
      if (micLine) {
        micLine.textContent = active ? formatSensorValue("MIC", data.MIC || {}) : "—";
        micLine.style.opacity = active ? "1" : "0.6";
        micLine.style.color = (data.MIC?.error) ? "#ef4444" : "";
      }
      const micSmall = qs("#mic-small");
      if (micSmall && data.MIC?.last_update) {
        micSmall.textContent = `Last: ${new Date(data.MIC.last_update).toLocaleTimeString()}`;
      }
      return;
    }

    const val = card.querySelector(".sensor-value");
    if (!val) return;

    if (!active) {
      val.textContent = "—";
      val.style.opacity = "0.6";
      val.style.color = "";
      return;
    }

    val.style.opacity = "1";
    const txt = formatSensorValue(name, data[name]);
    val.textContent = txt;
    val.style.color = (data[name]?.error) ? "#ef4444" : "";

    if (data[name]?.last_update) {
      setSmall(name, `Last: ${new Date(data[name].last_update).toLocaleTimeString()}`);
    }
  });

  updateBuzzerStatus(data.BUZZER || { on: false });
  updateLcdStatus(data.LCD_TOOL || { line1: "", line2: "" });
}

setInterval(updateDashboard, 900);
updateDashboard();

// -------------------------
// MIC WAVE (fast polling)
// -------------------------
const micCanvas = qs("#mic-wave");
const micCtx = micCanvas ? micCanvas.getContext("2d") : null;

let micLastCommandAt = null;

function drawMicWave(arr) {
  if (!micCanvas || !micCtx) return;
  const w = micCanvas.width;
  const h = micCanvas.height;

  micCtx.clearRect(0, 0, w, h);

  if (!arr || !arr.length) return;

  // normalize for visible plot
  let max = 0.0001;
  for (const v of arr) max = Math.max(max, v || 0);
  const scale = 0.95 / max;

  micCtx.beginPath();
  const mid = h * 0.5;

  for (let i = 0; i < arr.length; i++) {
    const x = (i / (arr.length - 1)) * w;
    const y = mid - (arr[i] * scale) * mid;
    if (i === 0) micCtx.moveTo(x, y);
    else micCtx.lineTo(x, y);
  }

  micCtx.stroke();
}

async function pollMicWave() {
  // Only poll if canvas exists on page
  if (!micCanvas) return;

  try {
    const res = await fetch("/api/mic_wave", { cache: "no-store" });
    const d = await safeJson(res);
    if (!res.ok || !d || d.ok === false) return;

    // update live wave
    drawMicWave(Array.isArray(d.wave) ? d.wave : []);

    // update mic line using mic_wave payload (more real-time)
    const micLine = qs("#mic-line");
    if (micLine) {
      const active = !!d.active;
      if (!active) {
        micLine.textContent = "—";
        micLine.style.opacity = "0.6";
      } else {
        const peak = (d.peak == null) ? "—" : Number(d.peak).toFixed(3);
        const rms  = (d.rms  == null) ? "—" : Number(d.rms).toFixed(3);

        const text = (d.text || "").trim();
        const partial = (d.partial || "").trim();
        const cmd = (d.command || "").trim();

        let speechLine = cmd
          ? `CMD: ${cmd}`
          : (text ? `Text: ${text}` : (partial ? `... ${partial}` : "Say: open / hello"));

        if (d.error) speechLine = `Error: ${d.error}`;

        micLine.textContent = `Peak: ${peak} • RMS: ${rms} • ${speechLine}`;
        micLine.style.opacity = "1";
        micLine.style.color = d.error ? "#ef4444" : "";
      }
    }

    const micSmall = qs("#mic-small");
    if (micSmall && d.last_update) {
      micSmall.textContent = `Last: ${new Date(d.last_update).toLocaleTimeString()}`;
    }

    // one-shot command handling (optional)
    if (d.command && d.command_at && d.command_at !== micLastCommandAt) {
      micLastCommandAt = d.command_at;

      // Example hook:
      // if (d.command === "open") { ... }
      // if (d.command === "hello") { ... }

      // Clear command so it doesn't re-trigger
      try { await postJSON("/api/mic_command", { clear: true }); } catch(e) {}
    }

  } catch (e) {
    // ignore; dashboard still works
  }
}

// fast poll to look live but not lag
setInterval(pollMicWave, 120);
pollMicWave();