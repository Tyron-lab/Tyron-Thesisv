/* =============================================
   SENSOR DASHBOARD – FRONTEND LOGIC (FULL)
   - Shows values for ALL sensors
   - Adds missing toggleRelay() / toggleServo()
   - ✅ LED_TOOL REMOVED
   - ✅ MIC added (INMP441)
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
    body: JSON.stringify(payload),
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

  // Exclude tools
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

  if (name === "MIC") {
    const peak = data.peak;
    const rms = data.rms;
    const claps = data.claps ?? 0;
    const p = (peak == null) ? "—" : Number(peak).toFixed(3);
    const r = (rms == null) ? "—" : Number(rms).toFixed(3);
    return `Peak: ${p} • RMS: ${r} • Claps: ${claps}`;
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
// Polling
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