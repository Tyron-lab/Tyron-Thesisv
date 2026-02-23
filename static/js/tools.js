/* =============================================
   SENSOR DASHBOARD – FRONTEND LOGIC (DIAGNOSTIC + FIXED)
============================================= */

const qs  = (sel, root = document) => root.querySelector(sel);
const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

async function safeJson(res) {
  try { return await res.json(); } catch { return null; }
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

function setSmall(cardId, text) {
  const card = document.getElementById(cardId);
  if (!card) return;
  const el = card.querySelector(".last-update");
  if (!el) return;
  el.textContent = text ?? "";
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
// Card toggles (BMP/MPU etc)
// -------------------------
qsa(".sensor-card:not(.disabled)").forEach(card => {
  const id = card.id;

  // Exclude non-sensor toggles
  if (id === "Relay" || id === "servomotor") return;
  if (id === "LED_TOOL" || id === "BUZZER" || id === "LCD_TOOL") return;

  card.addEventListener("click", async () => {
    const r = await postJSON("/api/toggle", { sensor: id });

    if (!r.ok || r.data?.ok === false) {
      const msg = r.data?.error || "Toggle failed";
      setCardText(id, `Error: ${msg}`, true);
      return;
    }

    // show backend-side init errors immediately if any
    if (r.data?.error) {
      setCardText(id, `Error: ${r.data.error}`, true);
    }
  });
});

// -------------------------
// Tool controls
// -------------------------
function ledToggle(color) {
  postJSON("/api/led", { color, action: "toggle" })
    .then(r => {
      if (!r.ok || r.data?.ok === false) setCardText("LED_TOOL", `Error: ${r.data?.error || "LED failed"}`, true);
    })
    .catch(e => setCardText("LED_TOOL", `Error: ${String(e)}`, true));
}

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

function buzzerForceOff() {
  postJSON("/api/buzzer", { mode: "force_off" })
    .then(r => {
      if (!r.ok || r.data?.ok === false) setCardText("BUZZER", `Error: ${r.data?.error || "Off failed"}`, true);
      else updateBuzzerStatus({ on: false });
    });
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

function formatSensorValue(name, data) {
  if (!data) return "—";
  if (data.error) return `Error: ${data.error}`;

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

  // Sensor cards
  qsa(".sensor-card").forEach(card => {
    const name = card.id;
    const isTool = (name === "LED_TOOL" || name === "BUZZER" || name === "LCD_TOOL");

    if (isTool) return;

    const active = !!state[name];
    card.classList.toggle("active", active);

    const val = card.querySelector(".sensor-value");
    if (!val) return;

    if (!active) {
      val.textContent = "—";
      val.style.opacity = "0.6";
      return;
    }

    val.style.opacity = "1";
    const txt = formatSensorValue(name, data[name]);
    val.textContent = txt;
    val.style.color = (data[name]?.error) ? "#ef4444" : "";

    if (data[name]?.last_update) setSmall(name, `Last: ${new Date(data[name].last_update).toLocaleTimeString()}`);
  });

  // Tool status cards
  updateBuzzerStatus(data.BUZZER || { on: false });
  updateLcdStatus(data.LCD_TOOL || { line1: "", line2: "" });
}

setInterval(updateDashboard, 900);
updateDashboard();

// expose to inline onclick in HTML
window.ledToggle = ledToggle;
window.buzzerToggle = buzzerToggle;
window.buzzerBeep = buzzerBeep;
window.buzzerForceOff = buzzerForceOff;
window.lcdSend = lcdSend;
window.lcdClear = lcdClear;