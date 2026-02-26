/* activity1.js
   Frontend expects:
   - Cards: .exercise-card (tabindex=0, role=button)
   - Run buttons:   button.run-btn[data-run="<exercise_id>"]
   - Stop buttons:  button.stop-btn[data-stop="<exercise_id>"]
   - Speak buttons: button.speak-btn[data-speak="<exercise_id>"]
   - Status: span.status[data-status-for="<exercise_id>"]
   Backend (server.py):
   - POST /api/exercise        { exercise_id: "<exercise_id>" }
   - POST /api/exercise_stop   {}
   - GET  /api/exercise_status {}
   - GET  /api/exercise_logs   {}

   Activity 5 Telemetry (server.py):
   - GET /api/a5/latest   -> latest MQTT message
   Activity 5 Commands (server.py):
   - POST /api/a5/command -> publish MQTT command JSON
*/

(() => {
  const API_RUN = "/api/exercise";
  const API_STOP = "/api/exercise_stop";
  const API_STATUS = "/api/exercise_status";
  const API_LOGS = "/api/exercise_logs";

  // Activity 5
  const API_A5_LATEST = "/api/a5/latest";
  const API_A5_COMMAND = "/api/a5/command";

  const qs = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ---------- helpers ----------
  async function postJSON(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    return { ok: res.ok, status: res.status, data, text };
  }

  async function getJSON(url) {
    const res = await fetch(url, { method: "GET", cache: "no-store" });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    return { ok: res.ok, status: res.status, data, text };
  }

  function setStatus(exId, text, state = "") {
    const el = qs(`[data-status-for="${CSS.escape(exId)}"]`);
    if (el) el.textContent = text;

    const card = qs(`.exercise-card[data-exercise="${CSS.escape(exId)}"]`);
    if (card) {
      card.classList.remove("state-running", "state-error", "state-missing");
      if (state) card.classList.add(state);
    }
  }

  // ---------- speech ----------
  function speak(text) {
    try {
      if (!("speechSynthesis" in window)) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1;
      u.pitch = 1;
      u.lang = "en-US";
      window.speechSynthesis.speak(u);
    } catch {}
  }

  // ---------- modal ----------
  const modal = qs("#exModal");
  const modalClose = qs("#modalClose");
  const modalTitle = qs("#modalTitle");
  const modalDesc = qs("#modalDesc");
  const modalMeta = qs("#modalMeta");
  const modalImg = qs("#modalImg");
  const modalImg2 = qs("#modalImg2");
  const modalRunBtn = qs("#modalRunBtn");
  const modalStopBtn = qs("#modalStopBtn");
  const modalSpeakBtn = qs("#modalSpeakBtn");

  // A5 EX21 live panel nodes
  const a5LivePanel = qs("#a5LivePanel");
  const a5Dot = qs("#a5Dot");
  const a5ConnText = qs("#a5ConnText");
  const a5Temp = qs("#a5Temp");
  const a5Motion = qs("#a5Motion");
  const a5Noise = qs("#a5Noise");
  const a5Updated = qs("#a5Updated");
  const a5Raw = qs("#a5Raw");

  // A5 EX22 command panel nodes
  const a5CmdPanel = qs("#a5CmdPanel");
  const a5CmdDot = qs("#a5CmdDot");
  const a5CmdText = qs("#a5CmdText");
  const a5CmdLast = qs("#a5CmdLast");
  const a5CmdRaw = qs("#a5CmdRaw");

  const cmdLightOn  = qs("#cmdLightOn");
  const cmdLightOff = qs("#cmdLightOff");
  const cmdGateOpen = qs("#cmdGateOpen");
  const cmdGateClose= qs("#cmdGateClose");
  const cmdLedGreen = qs("#cmdLedGreen");
  const cmdAllOff   = qs("#cmdAllOff");

  let modalExerciseId = null;

  // ----- A5 EX21 telemetry polling -----
  let a5Timer = null;

  function setA5Conn(state, text) {
    if (!a5Dot || !a5ConnText) return;
    a5Dot.classList.remove("ok", "bad");
    if (state === "ok") a5Dot.classList.add("ok");
    else if (state === "bad") a5Dot.classList.add("bad");
    a5ConnText.textContent = text || "";
  }

  function safeVal(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }

  async function pollA5Once() {
    const r = await getJSON(API_A5_LATEST);
    if (!r.ok || !r.data || !r.data.ok) {
      setA5Conn("bad", "Offline");
      if (a5Updated) a5Updated.textContent = "Last update: —";
      if (a5Temp) a5Temp.textContent = "—";
      if (a5Motion) a5Motion.textContent = "—";
      if (a5Noise) a5Noise.textContent = "—";
      if (a5Raw) a5Raw.textContent = "raw: —";
      return;
    }

    const connected = !!r.data.connected;
    setA5Conn(connected ? "ok" : "bad", connected ? "Connected" : "Disconnected");

    const payload = r.data.payload || null;
    const raw = r.data.raw || "";

    let t = payload && (payload.temperature ?? payload.temp ?? payload.Temperature);
    let m = payload && (payload.motion ?? payload.pir ?? payload.Motion);
    let n = payload && (payload.noise ?? payload.sound ?? payload.Noise);

    if (a5Temp) a5Temp.textContent = safeVal(t);
    if (a5Motion) a5Motion.textContent = safeVal(m);
    if (a5Noise) a5Noise.textContent = safeVal(n);

    if (a5Updated) a5Updated.textContent = "Last update: " + (r.data.last_update || "—");
    if (a5Raw) a5Raw.textContent = "raw: " + (raw ? raw : "—");
  }

  function startA5Telemetry() {
    if (!a5LivePanel) return;
    a5LivePanel.hidden = false;
    setA5Conn("warn", "Connecting…");
    if (a5Timer) clearInterval(a5Timer);
    pollA5Once().catch(() => {});
    a5Timer = setInterval(() => {
      pollA5Once().catch(() => {});
    }, 300);
  }

  function stopA5Telemetry() {
    if (a5Timer) clearInterval(a5Timer);
    a5Timer = null;
    if (a5LivePanel) a5LivePanel.hidden = true;
  }

  // ----- A5 EX22 command panel -----
  function setCmdState(state, text) {
    if (!a5CmdDot || !a5CmdText) return;
    a5CmdDot.classList.remove("ok", "bad");
    if (state === "ok") a5CmdDot.classList.add("ok");
    else if (state === "bad") a5CmdDot.classList.add("bad");
    a5CmdText.textContent = text || "";
  }

  async function sendA5Command(payload) {
    setCmdState("ok", "Sending…");
    if (a5CmdRaw) a5CmdRaw.textContent = "payload: " + JSON.stringify(payload);

    const { ok, data, text } = await postJSON(API_A5_COMMAND, payload);

    if (!ok || !data || data.ok !== true) {
      setCmdState("bad", "Failed");
      const msg = (data && (data.message || data.error)) ? (data.message || data.error) : (text || "Command failed");
      if (a5CmdLast) a5CmdLast.textContent = "Last command: ERROR";
      throw new Error(msg);
    }

    setCmdState("ok", "Sent ✅");
    if (a5CmdLast) a5CmdLast.textContent = "Last command: " + (payload.device || "cmd");
    return data;
  }

  function startA5Commands() {
    if (!a5CmdPanel) return;
    a5CmdPanel.hidden = false;
    setCmdState("ok", "Ready");
    if (a5CmdLast) a5CmdLast.textContent = "Last command: —";
    if (a5CmdRaw) a5CmdRaw.textContent = "payload: —";
  }

  function stopA5Commands() {
    if (a5CmdPanel) a5CmdPanel.hidden = true;
  }

  function bindCmdButtons() {
    // bind once
    if (cmdLightOn) {
      cmdLightOn.onclick = async () => {
        try { await sendA5Command({ device: "relay", ch: 1, state: "on" }); }
        catch (e) { alert(e.message); }
      };
    }
    if (cmdLightOff) {
      cmdLightOff.onclick = async () => {
        try { await sendA5Command({ device: "relay", ch: 1, state: "off" }); }
        catch (e) { alert(e.message); }
      };
    }
    if (cmdGateOpen) {
      cmdGateOpen.onclick = async () => {
        try { await sendA5Command({ device: "servo", angle: 90 }); }
        catch (e) { alert(e.message); }
      };
    }
    if (cmdGateClose) {
      cmdGateClose.onclick = async () => {
        try { await sendA5Command({ device: "servo", angle: 0 }); }
        catch (e) { alert(e.message); }
      };
    }
    if (cmdLedGreen) {
      cmdLedGreen.onclick = async () => {
        try { await sendA5Command({ device: "led", color: "green", state: "on" }); }
        catch (e) { alert(e.message); }
      };
    }
    if (cmdAllOff) {
      cmdAllOff.onclick = async () => {
        try {
          await sendA5Command({ device: "relay", ch: 1, state: "off" });
          await sendA5Command({ device: "relay", ch: 2, state: "off" });
          await sendA5Command({ device: "relay", ch: 3, state: "off" });
          await sendA5Command({ device: "relay", ch: 4, state: "off" });
          await sendA5Command({ device: "led", color: "red", state: "off" });
          await sendA5Command({ device: "led", color: "orange", state: "off" });
          await sendA5Command({ device: "led", color: "green", state: "off" });
          await sendA5Command({ device: "servo", angle: 0 });
        } catch (e) {
          alert(e.message);
        }
      };
    }
  }

  // bind command buttons immediately
  bindCmdButtons();

  function openModalFromCard(card) {
    if (!modal) return;
    const exId = card.dataset.exercise || "";
    modalExerciseId = exId;

    const title =
      card.dataset.sayTitle ||
      qs("h3", card)?.textContent?.trim() ||
      "Exercise";
    const desc =
      card.dataset.sayText ||
      qs(".ex-desc", card)?.textContent?.trim() ||
      "";

    if (modalTitle) modalTitle.textContent = title;
    if (modalDesc) modalDesc.textContent = desc;

    const img1 = card.dataset.image || "";
    const img2 = card.dataset.image2 || "";
    if (modalImg) {
      modalImg.src = img1;
      modalImg.alt = title;
      modalImg.hidden = !img1;
    }
    if (modalImg2) {
      modalImg2.src = img2;
      modalImg2.alt = title;
      modalImg2.hidden = !img2;
    }

    if (modalMeta) {
      modalMeta.innerHTML = "";
      const spans = qsa(".ex-meta span", card);
      spans.forEach((s) => {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = s.textContent.trim();
        modalMeta.appendChild(chip);
      });
    }

    if (modalRunBtn) modalRunBtn.onclick = () => runExercise(exId);
    if (modalStopBtn) modalStopBtn.onclick = () => stopExercise(exId);

    if (modalSpeakBtn) modalSpeakBtn.onclick = () => {
      const sayTitle = card.dataset.sayTitle || title;
      const sayText = card.dataset.sayText || desc;
      speak(`${sayTitle}. ${sayText}`);
    };

    // ✅ Only show/poll telemetry in popup when Exercise 21 is opened
    if (exId === "a5-ex21") startA5Telemetry();
    else stopA5Telemetry();

    // ✅ Only show command panel when Exercise 22 is opened
    if (exId === "a5-ex22") startA5Commands();
    else stopA5Commands();

    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
  }

  function closeModal() {
    if (!modal) return;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    modalExerciseId = null;

    stopA5Telemetry();
    stopA5Commands();
  }

  if (modalClose) modalClose.addEventListener("click", closeModal);
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  // ---------- run/stop logic ----------
  let currentRunningEx = null;

  async function runExercise(exId) {
    if (!exId) return;

    // stop any previous exercise first (backend runs one at a time)
    if (currentRunningEx && currentRunningEx !== exId) {
      await postJSON(API_STOP, {});
      setStatus(currentRunningEx, "Stopped");
      currentRunningEx = null;
    }

    setStatus(exId, "Running...", "state-running");

    // server expects { exercise_id: ... }
    const { ok, data, text } = await postJSON(API_RUN, { exercise_id: exId });

    if (!ok) {
      const errMsg = (data && data.error) ? data.error : (text || "Error");
      setStatus(exId, "Error", "state-error");
      console.warn("Run failed:", exId, errMsg);
      return;
    }

    currentRunningEx = exId;
    setStatus(exId, "Running...", "state-running");
  }

  async function stopExercise(requestedExId = null) {
    // If user presses stop for a specific card, only stop if it matches the running one
    if (requestedExId && currentRunningEx && requestedExId !== currentRunningEx) {
      setStatus(requestedExId, "Ready");
      return;
    }

    if (!currentRunningEx) {
      if (requestedExId) setStatus(requestedExId, "Ready");
      return;
    }

    const stoppingId = currentRunningEx;
    setStatus(stoppingId, "Stopping...");

    const { ok, data, text } = await postJSON(API_STOP, {});
    if (!ok) {
      const errMsg = (data && data.error) ? data.error : (text || "Stop error");
      setStatus(stoppingId, "Stop failed", "state-error");
      console.warn("Stop failed:", errMsg);
      return;
    }

    setStatus(stoppingId, "Stopped");
    currentRunningEx = null;
  }

  async function refreshStatus() {
    const r = await getJSON(API_STATUS);
    if (!r.ok) return;

    const running = !!(r.data && r.data.running);

    // if nothing is running but we had one, show logs once
    if (!running && currentRunningEx) {
      const finishedId = currentRunningEx;

      const logs = await getJSON(API_LOGS);
      const out = logs?.data?.stdout || "";
      const err = logs?.data?.stderr || "";

      if (err) setStatus(finishedId, "Finished (with errors)", "state-error");
      else setStatus(finishedId, "Finished");

      if (out) console.log("[Exercise stdout]\n" + out);
      if (err) console.warn("[Exercise stderr]\n" + err);

      currentRunningEx = null;
      return;
    }

    // show running state
    if (running && currentRunningEx) {
      setStatus(currentRunningEx, "Running...", "state-running");
    }
  }

  // ---------- bind cards ----------
  qsa(".exercise-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      const target = e.target;
      if (target && (target.closest("button") || target.closest("a"))) return;
      openModalFromCard(card);
    });

    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openModalFromCard(card);
      }
    });
  });

  // ---------- bind run/stop/speak buttons ----------
  qsa("button.run-btn[data-run]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      runExercise(btn.dataset.run);
    });
  });

  qsa("button.stop-btn[data-stop]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      stopExercise(btn.dataset.stop);
    });
  });

  qsa("button.speak-btn[data-speak]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const exId = btn.dataset.speak;
      const card = qs(`.exercise-card[data-exercise="${CSS.escape(exId)}"]`);
      if (!card) return;
      const title = card.dataset.sayTitle || qs("h3", card)?.textContent || "Exercise";
      const text = card.dataset.sayText || qs(".ex-desc", card)?.textContent || "";
      speak(`${title}. ${text}`);
    });
  });

  // ---------- initial ----------
  qsa(".exercise-card[data-exercise]").forEach((card) => {
    const exId = card.dataset.exercise;
    setStatus(exId, "Ready");
  });

  // poll status every 1s
  setInterval(() => {
    refreshStatus().catch(() => {});
  }, 1000);
})();