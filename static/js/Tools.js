/* =============================================
   SENSOR DASHBOARD – FRONTEND LOGIC
   Servo behavior:
   - ON  → servo to 90° and hold (powered)
   - OFF → servo PWM off, no holding torque
============================================= */

const sensorCards = document.querySelectorAll(".sensor-card:not(.disabled)");

// Toggle regular sensors (exclude Relay & servomotor)
sensorCards.forEach(card => {
    const id = card.id;
    if (id === "Relay" || id === "servomotor") return;

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
    .then(data => {
        const el = document.getElementById("relay-status");
        const card = document.getElementById("Relay");
        if (el && card) {
            if (data.active) {
                el.textContent = "ON";
                el.style.color = "#22c55e";
                card.classList.add("active");
            } else {
                el.textContent = "OFF";
                el.style.color = "#ef4444";
                card.classList.remove("active");
            }
        }
    })
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
    .then(data => {
        const statusEl = document.getElementById("servo-status");
        const cardEl = document.getElementById("servomotor");

        if (!statusEl || !cardEl) return;

        if (data.active) {
            statusEl.textContent = "ON – 90°";
            statusEl.style.color = "#22c55e";
            cardEl.classList.add("active");
        } else {
            statusEl.textContent = "OFF";
            statusEl.style.color = "#ef4444";
            cardEl.classList.remove("active");
        }
    })
    .catch(err => console.error("Servo toggle failed:", err));
}

// Format sensor values for display
function formatSensorValue(name, data) {
    if (!data) return "—";

    switch (name) {
        case "DHT11":
            return data.temperature != null && data.humidity != null
                ? `${data.temperature} °C • ${data.humidity}%`
                : "Reading...";

        case "BMP280":
            return data.temperature != null
                ? `${data.temperature} °C • ${data.pressure} hPa • ${data.altitude} m`
                : "Reading...";

        case "MPU6050":
            if (data.acceleration?.x != null) {
                return `Acc: ${data.acceleration.x.toFixed(2)} ${data.acceleration.y.toFixed(2)} ${data.acceleration.z.toFixed(2)} m/s²<br>` +
                       `Gyro: ${data.gyro?.x?.toFixed(1)} ${data.gyro?.y?.toFixed(1)} ${data.gyro?.z?.toFixed(1)} °/s`;
            }
            return "Reading...";

        case "PIR":
            return data.motion ? `MOTION! (${data.count || 0})` : "No motion";

        case "ULTRASONIC":
            return data.distance_cm != null && data.distance_cm >= 2 && data.distance_cm <= 400
                ? `${data.distance_cm} cm`
                : "Out of range / No echo";

        case "MHMQ":
            return data.gas_detected ? "Gas Detected!" : "Clear";

        case "Relay":
            return "Click to toggle all";

        case "servomotor":
            return data.angle != null ? `Angle: ${data.angle}°` : "—";

        default:
            return "—";
    }
}

// Main dashboard update function
async function updateDashboard() {
    try {
        const res = await fetch("/api/sensors");
        if (!res.ok) throw new Error("Backend error");

        const state = await res.json();
        const data = state.data || {};

        document.querySelectorAll(".sensor-card").forEach(card => {
            const name = card.id;
            const isActive = state[name] === true;

            card.classList.toggle("active", isActive);

            let valueEl = card.querySelector(".sensor-value");
            if (valueEl) {
                if (name === "Relay") {
                    const allOn = data.Relay?.ch1 && data.Relay?.ch2 &&
                                  data.Relay?.ch3 && data.Relay?.ch4;
                    document.getElementById("relay-status").textContent = 
                        allOn ? "ON" : "OFF";
                    valueEl.style.color = allOn ? "#22c55e" : "#ef4444";
                } else if (name === "servomotor") {
                    valueEl.textContent = isActive 
                        ? "ON – 90°"
                        : "OFF";
                    valueEl.style.color = isActive ? "#22c55e" : "#ef4444";
                } else if (isActive && data[name]) {
                    valueEl.innerHTML = formatSensorValue(name, data[name]);  // use innerHTML for <br>
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

// Start polling
setInterval(updateDashboard, 900);
updateDashboard();  // Initial load