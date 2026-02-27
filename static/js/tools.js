/* =============================================
   SENSOR DASHBOARD – FRONTEND LOGIC
   - LED completely removed
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

function setCardText(cardId, text, isError = false) {
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

// Sensor card toggles (skip relay/servo since they use inline onclick)
qsa(".sensor-card:not(.disabled)").forEach(card => {
  const id = card.id;
  if (id === "Relay" || id === "servomotor") return;

  card.addEventListener("click", async () => {
    const active = card.classList.toggle("active");
    const { ok, data } = await postJSON("/api/toggle", { name: id, active });
    if (!ok) {
      card.classList.toggle("active", !active); // revert on failure
      console.error(`Toggle ${id} failed:`, data?.error);
    }
  });
});

// Relay channel toggles
async function toggleRelay(channel) {
  const { ok, data } = await postJSON("/api/toggle", { name: "Relay", channel });
  if (!ok) {
    console.error(`Toggle Relay ${channel} failed:`, data?.error);
  } else {
    updateDashboard(); // refresh UI
  }
}

// Servo angle slider
const servoSlider = qs("#servo-angle");
if (servoSlider) {
  servoSlider.addEventListener("input", async (e) => {
    const angle = parseInt(e.target.value, 10);
    const { ok, data } = await postJSON("/api/toggle", { name: "servomotor", angle });
    if (!ok) {
      console.error("Servo angle failed:", data?.error);
    } else {
      qs("#servo-value").textContent = `${angle}°`;
    }
  });
}

// Buzzer toggle (if using card click) – optional if you have direct button
async function buzzerToggle() {
  const card = qs("#BUZZER");
  if (!card) return;
  const active = card.classList.toggle("active");
  const { ok, data } = await postJSON("/api/toggle", { name: "BUZZER", active });
  if (!ok) {
    card.classList.toggle("active", !active);
    console.error("Buzzer toggle failed:", data?.error);
  }
}

// LCD send / clear
async function lcdSend() {
  const line1 = qs("#lcd-line1")?.value ?? "";
  const line2 = qs("#lcd-line2")?.value ?? "";
  const { ok, data } = await postJSON("/api/toggle", { name: "LCD_TOOL", line1, line2 });
  if (!ok) console.error("LCD send failed:", data?.error);
}

async function lcdClear() {
  const { ok, data } = await postJSON("/api/toggle", { name: "LCD_TOOL", clear: true });
  if (!ok) {
    console.error("LCD clear failed:", data?.error);
  } else {
    qs("#lcd-line1").value = "";
    qs("#lcd-line2").value = "";
  }
}

// Formatting for display
function formatSensorValue(name, data) {
  if (!data || data.error) return data?.error ?? "Error";

  switch (name) {
    case "MPU6050":
      const { ax, ay, az, gx, gy, gz } = data;
      return `A: (${ax?.toFixed(2)}, ${ay?.toFixed(2)}, ${az?.toFixed(2)}) m/s²\nG: (${gx?.toFixed(2)}, ${gy?.toFixed(2)}, ${gz?.toFixed(2)}) °/s`;
    case "BMP280":
      return `Temp: ${data.temperature?.toFixed(1)}°C\nPressure: ${data.pressure?.toFixed(0)} hPa`;
    case "DHT11":
      return `Temp: ${data.temperature?.toFixed(1)}°C\nHumidity: ${data.humidity?.toFixed(0)}%`;
    case "Relay":
      return `CH1: ${data.ch1 ? "ON" : "OFF"} • CH2: ${data.ch2 ? "ON" : "OFF"}\nCH3: ${data.ch3 ? "ON" : "OFF"} • CH4: ${data.ch4 ? "ON" : "OFF"}`;
    case "servomotor":
      return `Angle: ${data.angle ?? 90}°`;
    case "BUZZER":
      return data.on ? "Beeping" : "Off";
    case "LCD_TOOL":
      return `${data.line1 ?? ""}\n${data.line2 ?? ""}`;
    default:
      return JSON.stringify(data, null, 2);
  }
}

// Buzzer status update
function updateBuzzerStatus(data) {
  const card = qs("#BUZZER");
  if (!card) return;
  const active = !!data.on;
  card.classList.toggle("active", active);
  const val = qs(".sensor-value", card);
  if (val) val.textContent = active ? "Beeping" : "Off";
}

// LCD status update
function updateLcdStatus(data) {
  const card = qs("#LCD_TOOL");
  if (!card) return;
  const val = qs(".sensor-value", card);
  if (val) val.textContent = `${data.line1 ?? ""}\n${data.line2 ?? ""}`;
}

// Main dashboard refresh
async function updateDashboard() {
  const res = await fetch("/api/sensors");
  const data = await safeJson(res);
  if (!data || !data.ok) return;

  qsa(".sensor-card").forEach(card => {
    const name = card.id;
    if (!data[name]) return;

    const active = !!data[name].active;
    card.classList.toggle("active", active);

    // Relay special UI
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

    // Servo special UI
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

    // Normal sensor value
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

  // Update tool status (no LED)
  updateBuzzerStatus(data.BUZZER || { on: false });
  updateLcdStatus(data.LCD_TOOL || { line1: "", line2: "" });
}

setInterval(updateDashboard, 900);
updateDashboard();