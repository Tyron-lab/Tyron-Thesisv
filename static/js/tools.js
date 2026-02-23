/* =============================================
   SENSOR DASHBOARD – FRONTEND LOGIC
============================================= */

const sensorCards = document.querySelectorAll(".sensor-card:not(.disabled)");

// Toggle regular sensors (exclude Relay/servo and tool cards)
sensorCards.forEach(card => {
  const id = card.id;
  if (id === "Relay" || id === "servomotor") return;
  if (id === "LED_TOOL" || id === "BUZZER" || id === "LCD_TOOL") return;

  card.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sensor: id })
      });
      if (!res.ok) console.error(`Toggle failed for ${id}`);
    } catch (err) {
      console.error("Toggle error:", err);
    }
  });
});

// Relay toggle - all channels
function toggleRelay() {
  fetch("/api/toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sensor: "Relay" })
  })
    .then(r => r.json())
    .catch(err => console.error("Relay toggle failed:", err));
}

// Servo ON/OFF toggle
function toggleServo() {
  fetch("/api/toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sensor: "servomotor" })
  })
    .then(r => r.json())
    .catch(err => console.error("Servo toggle failed:", err));
}

// ────────────────────────────────────────────────
// TOOL CONTROLS
// ────────────────────────────────────────────────
function ledToggle(color) {
  fetch("/api/led", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ color, action: "toggle" })
  })
    .then(r => r.json())
    .then(data => {
      if (data?.all) {
        updateLedStatus(data.all);
      }
    })
    .catch(err => console.error("LED toggle failed:", err));
}

function buzzerToggle() {
  fetch("/api/buzzer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "toggle" })
  })
    .then(r => r.json())
    .catch(err => console.error("Buzzer toggle failed:", err));
}

function buzzerBeep() {
  fetch("/api/buzzer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "beep", count: 2, on_ms: 120, off_ms: 120 })
  })
    .then(r => r.json())
    .catch(err => console.error("Buzzer beep failed:", err));
}

function lcdSend() {
  const line1 = (document.getElementById("lcd-line1")?.value || "").trim();
  const line2 = (document.getElementById("lcd-line2")?.value || "").trim();

  fetch("/api/lcd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ line1, line2 })
  })
    .then(r => r.json())
    .catch(err => console.error("LCD send failed:", err));
}

function lcdClear() {
  fetch("/api/lcd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clear: true })
  })
    .then(r => r.json())
    .catch(err => console.error("LCD clear failed:", err));
}

// ────────────────────────────────────────────────
// DISPLAY FORMATTERS
// ────────────────────────────────────────────────
function formatSensorValue(name, data) {
  if (!data) return "—";

  switch (name) {
    case "DHT11":
      return data.temperature != null && data.humidity != null
        ? `${data.temperature} °C • ${data.humidity}%`
        : "Reading...";

    case "BMP280":
      return data.temperature != null && data.pressure != null
        ? `${data.temperature} °C • ${data.pressure} hPa • ${data.altitude ?? "—"} m`
        : "Reading...";

    case "MPU6050": {
      const ax = data.ax, ay = data.ay, az = data.az;
      const gx = data.gx, gy = data.gy, gz = data.gz;
      const fmt = (v) => (typeof v === "number" ? v.toFixed(2) : v);
      if (ax != null && ay != null && az != null && gx != null && gy != null && gz != null) {
        return `A:${fmt(ax)},${fmt(ay)},${fmt(az)} • G:${fmt(gx)},${fmt(gy)},${fmt(gz)}`;
      }
      return "Reading...";
    }

    case "PIR":
      return data.motion ? `MOTION! (${data.count || 0})` : "No motion";

    case "ULTRASONIC":
      return data.distance_cm != null && data.distance_cm >= 2 && data.distance_cm <= 400
        ? `${data.distance_cm} cm`
        : "Out of range / No echo";

    case "MHMQ": {
      const lvl = (data.level_percent != null) ? `${data.level_percent}%` : "—";
      return data.gas_detected ? `Gas Detected! (${lvl})` : `Clear (${lvl})`;
    }

    default:
      return "—";
  }
}

function updateLedStatus(ledData) {
  const el = document.getElementById("led-status");
  if (!el || !ledData) return;

  const r = ledData.red ? "ON" : "OFF";
  const o = ledData.orange ? "ON" : "OFF";
  const g = ledData.green ? "ON" : "OFF";
  el.textContent = `red:${r} • orange:${o} • green:${g}`;
}

function updateBuzzerStatus(buzData) {
  const el = document.getElementById("buzzer-status");
  if (!el || !buzData) return;
  el.textContent = buzData.on ? "ON" : "OFF";
  el.style.color = buzData.on ? "#22c55e" : "#ef4444";
}

function updateLcdStatus(lcdData) {
  const el = document.getElementById("lcd-status");
  if (!el || !lcdData) return;
  const l1 = (lcdData.line1 || "").slice(0, 16);
  const l2 = (lcdData.line2 || "").slice(0, 16);
  el.textContent = (l1 || l2) ? `${l1} | ${l2}` : "—";
}

// ────────────────────────────────────────────────
// MAIN POLLING
// ────────────────────────────────────────────────
async function updateDashboard() {
  try {
    const res = await fetch("/api/sensors");
    if (!res.ok) throw new Error("Backend error");

    const state = await res.json();
    const data = state.data || {};

    document.querySelectorAll(".sensor-card").forEach(card => {
      const name = card.id;

      // Tool cards: driven by sensor_data only
      if (name === "LED_TOOL") {
        updateLedStatus(data.LED_TOOL);
      }
      if (name === "BUZZER") {
        updateBuzzerStatus(data.BUZZER);
      }
      if (name === "LCD_TOOL") {
        updateLcdStatus(data.LCD_TOOL);
      }

      // Active highlight only for real sensors (not tools)
      const isTool = (name === "LED_TOOL" || name === "BUZZER" || name === "LCD_TOOL");
      const isActive = isTool ? true : (state[name] === true);
      card.classList.toggle("active", isActive && !isTool);

      let valueEl = card.querySelector(".sensor-value");
      if (!valueEl) return;

      if (name === "Relay") {
        const allOn = data.Relay?.ch1 && data.Relay?.ch2 && data.Relay?.ch3 && data.Relay?.ch4;
        const el = document.getElementById("relay-status");
        if (el) {
          el.textContent = allOn ? "ON" : "OFF";
          el.style.color = allOn ? "#22c55e" : "#ef4444";
        }
        return;
      }

      if (name === "servomotor") {
        const el = document.getElementById("servo-status");
        if (el) {
          el.textContent = (state.servomotor === true) ? "ON – 90°" : "OFF";
          el.style.color = (state.servomotor === true) ? "#22c55e" : "#ef4444";
        }
        return;
      }

      // Tool cards already handled
      if (isTool) return;

      if (isActive && data[name]) {
        valueEl.textContent = formatSensorValue(name, data[name]);
        valueEl.style.opacity = "1";

        if (name === "PIR" && data[name]?.motion) {
          card.classList.add("motion-alert");
        } else {
          card.classList.remove("motion-alert");
        }
      } else {
        valueEl.textContent = isActive ? "Waiting..." : "—";
        valueEl.style.opacity = "0.6";
      }

      // Last update timestamp
      const timeEl = card.querySelector(".last-update");
      if (data[name]?.last_update && isActive) {
        const t = new Date(data[name].last_update);
        if (timeEl) timeEl.textContent = `Last: ${t.toLocaleTimeString()}`;
      } else if (timeEl) {
        timeEl.textContent = "";
      }
    });

  } catch (err) {
    console.error("Dashboard update failed:", err);
  }
}

setInterval(updateDashboard, 900);
updateDashboard();