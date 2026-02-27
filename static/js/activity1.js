/* activity1.js — FULL UPDATED
   MODE A (default): Activities behave like Tools (use /api/toggle + live status across phones)
   MODE B (optional): SHIFT + click "Run" to run the actual Exercise#.py via /api/exercise
   Multi-phone lock: /api/focus

   Requires server.py:
     - /api/focus
     - /api/toggle
     - /api/sensors
     - /api/exercise /api/exercise_stop /api/exercise_status /api/exercise_logs
     - /api/a5/latest /api/a5/command
*/

(() => {
  const API_TOGGLE = "/api/toggle";
  const API_SENSORS = "/api/sensors";

  const API_RUN = "/api/exercise";
  const API_STOP = "/api/exercise_stop";
  const API_STATUS = "/api/exercise_status";
  const API_LOGS = "/api/exercise_logs";

  const API_A5_LATEST = "/api/a5/latest";
  const API_A5_COMMAND = "/api/a5/command";

  const API_FOCUS = "/api/focus";

  const qs = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

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

  // Activity 1–4 mapping to Tools sensors (MODE A)
  const EX_TOGGLE_MAP = {
    "a1-ex1": ["PIR"],
    "a1-ex2": ["MHMQ"],
    "a1-ex3": ["DHT11", "LCD_TOOL"],
    "a1-ex4": ["ULTRASONIC", "BUZZER"],
    "a1-ex5": ["BMP280", "LCD_TOOL"],

    "a2-ex6": ["DHT11", "PIR", "MHMQ"],
    "a2-ex7": ["MHMQ"],
    "a2-ex8": ["PIR"],
    "a2-ex9": ["DHT11", "BUZZER"],
    "a2-ex10": ["DHT11", "PIR", "MHMQ", "BMP280"],

    "a3-ex11": ["BMP280", "LCD_TOOL"],
    "a3-ex12": ["MPU6050"],
    "a3-ex13": ["LCD_TOOL"],
    "a3-ex14": ["BMP280", "MPU6050", "LCD_TOOL"],
    "a3-ex15": ["BMP280", "MPU6050", "LCD_TOOL"],

    "a4-ex16": ["Relay"],
    "a4-ex17": ["Relay"],
    "a4-ex18": ["BUZZER"],
    "a4-ex19": ["Relay"],
    "a4-ex20": ["Relay"],
  };

  // Activity 5 still uses runner/MQTT
  const EX_RUNNER_SET = new Set(["a5-ex21", "a5-ex22", "a5-ex23", "a5-ex24", "a5-ex25"]);

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

  // A5 EX21 live panel
  const a5LivePanel = qs("#a5LivePanel");
  const a5Dot = qs("#a5Dot");
  const a5ConnText = qs("#a5ConnText");
  const a5Temp = qs("#a5Temp");
  const a5Motion = qs("#a5Motion");
  const a5Noise = qs("#a5Noise");
  const a5Updated = qs("#a5Updated");
  const a5Raw = qs("#a5Raw");

  // A5 EX22 commands panel
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

  // A5 EX23 storage
  const a5StorePanel   = qs("#a5StorePanel");
  const a5StoreDot     = qs("#a5StoreDot");
  const a5StoreText    = qs("#a5StoreText");
  const a5StorePath    = qs("#a5StorePath");
  const a5StoreLast    = qs("#a5StoreLast");
  const a5StoreCount   = qs("#a5StoreCount");
  const a5StoreUpdated = qs("#a5StoreUpdated");
  const a5StoreRaw     = qs("#a5StoreRaw");

  let modalExerciseId = null;

  // ---------- busy/lock UI (multi-phone focus) ----------
  let currentRunningEx = null;

  function setBusyUI(runningExId) {
    const hasRunning = !!runningExId;

    qsa(".exercise-card[data-exercise]").forEach((card) => {
      const exId = card.dataset.exercise;
      const isThis = hasRunning && exId === runningExId;

      if (hasRunning && !isThis) {
        if (card.dataset.prevTabindex === undefined) {
          card.dataset.prevTabindex = card.getAttribute("tabindex") ?? "";
        }
        card.setAttribute("aria-disabled", "true");
        card.setAttribute("tabindex", "-1");
        card.style.pointerEvents = "none";
        card.style.opacity = "0.55";
        card.style.filter = "grayscale(0.35)";
      } else {
        card.removeAttribute("aria-disabled");
        const prev = card.dataset.prevTabindex;
        if (prev !== undefined) {
          if (prev === "") card.removeAttribute("tabindex");
          else card.setAttribute("tabindex", prev);
          delete card.dataset.prevTabindex;
        }
        card.style.pointerEvents = "";
        card.style.opacity = "";
        card.style.filter = "";
      }

      const btns = qsa("button", card);
      btns.forEach((btn) => {
        const isStop = btn.classList.contains("stop-btn") || btn.hasAttribute("data-stop");
        const allow = !hasRunning || isThis || (isThis && isStop);

        if (!allow) {
          btn.disabled = true;
          btn.setAttribute("aria-disabled", "true");
          btn.style.pointerEvents = "none";
          btn.style.opacity = "0.6";
        } else {
          btn.disabled = false;
          btn.removeAttribute("aria-disabled");
          btn.style.pointerEvents = "";
          btn.style.opacity = "";
        }
      });
    });

    if (hasRunning && modalExerciseId && modalExerciseId !== runningExId) {
      if (modalRunBtn) modalRunBtn.disabled = true;
      if (modalSpeakBtn) modalSpeakBtn.disabled = true;
    } else {
      if (modalRunBtn) modalRunBtn.disabled = false;
      if (modalSpeakBtn) modalSpeakBtn.disabled = false;
    }
  }

  async function setFocus(exId, running) {
    const by = (navigator.userAgent || "phone").slice(0, 40);
    await postJSON(API_FOCUS, { exercise_id: exId, running: !!running, by }).catch(() => {});
  }

  async function syncFocusFromServer() {
    const r = await getJSON(API_FOCUS);
    if (!r.ok || !r.data) return;

    const running = !!r.data.running;
    const exId = r.data.exercise_id || null;

    if (!running) {
      if (currentRunningEx) {
        currentRunningEx = null;
        setBusyUI(null);
      }
      return;
    }

    if (exId && exId !== currentRunningEx) {
      currentRunningEx = exId;
      setBusyUI(currentRunningEx);
      setStatus(currentRunningEx, "Running...", "state-running");
    }
  }

  // ---------- A5 helpers ----------
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

    const t = payload && (payload.temperature ?? payload.temp ?? payload.Temperature);
    const m = payload && (payload.motion ?? payload.pir ?? payload.Motion);
    const n = payload && (payload.noise ?? payload.sound ?? payload.Noise);

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
    a5Timer = setInterval(() => { pollA5Once().catch(() => {}); }, 300);
  }

  function stopA5Telemetry() {
    if (a5Timer) clearInterval(a5Timer);
    a5Timer = null;
    if (a5LivePanel) a5LivePanel.hidden = true;
  }

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
    if (cmdLightOn)  cmdLightOn.onclick  = async () => { try { await sendA5Command({ device:"relay", ch:1, state:"on" }); } catch(e){ alert(e.message);} };
    if (cmdLightOff) cmdLightOff.onclick = async () => { try { await sendA5Command({ device:"relay", ch:1, state:"off"}); } catch(e){ alert(e.message);} };
    if (cmdGateOpen) cmdGateOpen.onclick = async () => { try { await sendA5Command({ device:"servo", angle:90}); } catch(e){ alert(e.message);} };
    if (cmdGateClose)cmdGateClose.onclick= async () => { try { await sendA5Command({ device:"servo", angle:0}); } catch(e){ alert(e.message);} };
    if (cmdLedGreen) cmdLedGreen.onclick = async () => { try { await sendA5Command({ device:"led", color:"green", state:"on"}); } catch(e){ alert(e.message);} };
    if (cmdAllOff) cmdAllOff.onclick = async () => {
      try {
        await sendA5Command({ device:"relay", ch:1, state:"off" });
        await sendA5Command({ device:"relay", ch:2, state:"off" });
        await sendA5Command({ device:"relay", ch:3, state:"off" });
        await sendA5Command({ device:"relay", ch:4, state:"off" });
        await sendA5Command({ device:"led", color:"red", state:"off" });
        await sendA5Command({ device:"led", color:"orange", state:"off" });
        await sendA5Command({ device:"led", color:"green", state:"off" });
        await sendA5Command({ device:"servo", angle:0 });
      } catch(e){ alert(e.message); }
    };
  }
  bindCmdButtons();

  // A5 EX23 storage polling
  let a5StoreTimer = null;
  let a5StoreLastLine = "";

  function setStoreState(state, text) {
    if (!a5StoreDot || !a5StoreText) return;
    a5StoreDot.classList.remove("ok", "bad");
    if (state === "ok") a5StoreDot.classList.add("ok");
    else if (state === "bad") a5StoreDot.classList.add("bad");
    a5StoreText.textContent = text || "";
  }

  function startA5StoragePanel() {
    if (!a5StorePanel) return;
    a5StorePanel.hidden = false;
    setStoreState("ok", "Running / Waiting for data…");
    a5StoreLastLine = "";

    if (a5StorePath) a5StorePath.textContent = "activity5/logs/ex23_events.csv + ex23_events.jsonl";
    if (a5StoreLast) a5StoreLast.textContent = "—";
    if (a5StoreCount) a5StoreCount.textContent = "0";
    if (a5StoreUpdated) a5StoreUpdated.textContent = "Last update: —";
    if (a5StoreRaw) a5StoreRaw.textContent = "raw: —";

    if (a5StoreTimer) clearInterval(a5StoreTimer);

    a5StoreTimer = setInterval(async () => {
      try {
        const logs = await getJSON(API_LOGS);
        const out = logs?.data?.stdout || "";
        const err = logs?.data?.stderr || "";

        if (err) {
          setStoreState("bad", "Error");
          if (a5StoreRaw) a5StoreRaw.textContent = "raw: " + err.slice(-180);
          return;
        }

        const lines = out.split(/\r?\n/).filter(Boolean);
        const ex23Lines = lines.filter(l => l.includes("[EX23]"));
        if (a5StoreCount) a5StoreCount.textContent = String(ex23Lines.length);

        const last = ex23Lines.length ? ex23Lines[ex23Lines.length - 1] : "";
        if (last && last !== a5StoreLastLine) {
          a5StoreLastLine = last;
          if (a5StoreLast) a5StoreLast.textContent = last.replace("[EX23]", "").trim() || last;
          if (a5StoreUpdated) a5StoreUpdated.textContent = "Last update: " + new Date().toLocaleTimeString();
          if (a5StoreRaw) a5StoreRaw.textContent = "raw: " + last;
          setStoreState("ok", "Saving ✅");
        } else {
          setStoreState("ok", "Running / Waiting for data…");
        }
      } catch {
        setStoreState("bad", "Offline");
      }
    }, 800);
  }

  function stopA5StoragePanel() {
    if (a5StoreTimer) clearInterval(a5StoreTimer);
    a5StoreTimer = null;
    if (a5StorePanel) a5StorePanel.hidden = true;
  }

  // ---------- modal open/close ----------
  function openModalFromCard(card) {
    if (!modal) return;
    const exId = card.dataset.exercise || "";
    modalExerciseId = exId;

    const title = card.dataset.sayTitle || qs("h3", card)?.textContent?.trim() || "Exercise";
    const desc  = card.dataset.sayText  || qs(".ex-desc", card)?.textContent?.trim() || "";

    if (modalTitle) modalTitle.textContent = title;
    if (modalDesc) modalDesc.textContent = desc;

    const img1 = card.dataset.image || "";
    const img2 = card.dataset.image2 || "";
    if (modalImg)  { modalImg.src = img1;  modalImg.alt = title; modalImg.hidden  = !img1; }
    if (modalImg2) { modalImg2.src = img2; modalImg2.alt = title; modalImg2.hidden = !img2; }

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

    if (modalRunBtn)  modalRunBtn.onclick  = () => startExercise(exId, false);
    if (modalStopBtn) modalStopBtn.onclick = () => stopExercise(exId);
    if (modalSpeakBtn) modalSpeakBtn.onclick = () => speak(`${title}. ${desc}`);

    if (exId === "a5-ex21") startA5Telemetry(); else stopA5Telemetry();
    if (exId === "a5-ex22") startA5Commands();  else stopA5Commands();
    if (exId === "a5-ex23") startA5StoragePanel(); else stopA5StoragePanel();

    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    setBusyUI(currentRunningEx);
  }

  function closeModal() {
    if (!modal) return;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    modalExerciseId = null;

    stopA5Telemetry();
    stopA5Commands();
    stopA5StoragePanel();
  }

  if (modalClose) modalClose.addEventListener("click", closeModal);
  if (modal) {
    modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  // ---------- MODE A: toggle helper ----------
  async function toggleOnce(sensor) {
    const { ok, data, text } = await postJSON(API_TOGGLE, { sensor });
    if (!ok || !data || data.ok === false) {
      throw new Error((data && (data.error || data.message)) || text || "Toggle failed");
    }
    return data;
  }

  // ---------- START/STOP ----------
  async function startExercise(exId, forceScriptMode) {
    if (!exId) return;

    await syncFocusFromServer();
    if (currentRunningEx && currentRunningEx !== exId) {
      setStatus(exId, `BUSY (running: ${currentRunningEx})`);
      setBusyUI(currentRunningEx);
      return;
    }

    await setFocus(exId, true);
    currentRunningEx = exId;
    setBusyUI(currentRunningEx);
    setStatus(exId, "Running...", "state-running");

    // MODE B: SHIFT run => run python script
    if (forceScriptMode) {
      const { ok, data, text } = await postJSON(API_RUN, { exercise_id: exId });
      if (!ok) {
        await setFocus(exId, false);
        currentRunningEx = null;
        setBusyUI(null);
        setStatus(exId, "Error", "state-error");
        throw new Error((data && (data.error || data.message)) || text || "Run failed");
      }
      return;
    }

    // Activity 5 always uses runner/MQTT (even in mode A)
    if (EX_RUNNER_SET.has(exId)) {
      const { ok, data, text } = await postJSON(API_RUN, { exercise_id: exId });
      if (!ok) {
        await setFocus(exId, false);
        currentRunningEx = null;
        setBusyUI(null);
        setStatus(exId, "Error", "state-error");
        throw new Error((data && (data.error || data.message)) || text || "Run failed");
      }
      return;
    }

    // MODE A: Activities 1–4 behave like Tools => toggle sensors
    const sensors = EX_TOGGLE_MAP[exId] || [];
    try {
      for (const s of sensors) await toggleOnce(s);
    } catch (e) {
      await setFocus(exId, false);
      currentRunningEx = null;
      setBusyUI(null);
      setStatus(exId, "Error", "state-error");
      throw e;
    }
  }

  async function stopExercise(requestedExId = null) {
    await syncFocusFromServer();

    if (!currentRunningEx) {
      if (requestedExId) setStatus(requestedExId, "Ready");
      setBusyUI(null);
      return;
    }

    if (requestedExId && requestedExId !== currentRunningEx) {
      setStatus(requestedExId, `BUSY (running: ${currentRunningEx})`);
      setBusyUI(currentRunningEx);
      return;
    }

    const exId = currentRunningEx;
    setStatus(exId, "Stopping...");

    // Stop runner scripts (covers Activity5 and ModeB scripts)
    const { ok } = await postJSON(API_STOP, {});
    // ok can be false when nothing is running on backend; that’s fine for Mode A toggles

    if (!EX_RUNNER_SET.has(exId) && !ok) {
      // MODE A only: toggle mapped sensors OFF (best-effort: toggle once each)
      const sensors = EX_TOGGLE_MAP[exId] || [];
      for (const s of sensors) {
        try { await toggleOnce(s); } catch {}
      }
    }

    await setFocus(exId, false);
    setStatus(exId, "Stopped");
    currentRunningEx = null;
    setBusyUI(null);
  }

  // Runner watcher: if script ends, clear focus
  async function refreshRunnerStatusIfNeeded() {
    if (!currentRunningEx) return;

    const r = await getJSON(API_STATUS);
    if (!r.ok || !r.data) return;

    const running = !!r.data.running;
    if (!running) {
      const finishedId = currentRunningEx;
      await setFocus(finishedId, false);
      currentRunningEx = null;
      setBusyUI(null);
      setStatus(finishedId, "Finished");
    }
  }

  // ---------- LIVE STATUS TEXT (all activities) ----------
  function fmt(n, digits = 1) {
    if (n === null || n === undefined) return "—";
    if (typeof n !== "number") return String(n);
    return n.toFixed(digits);
  }

  function computeExStatus(exId, sensorsResp) {
    const data = sensorsResp?.data || {};

    if (exId === "a1-ex1") {
      const pir = data.PIR || {};
      return `PIR: ${pir.motion ? "MOTION" : "NO"} • Count: ${pir.count ?? 0}`;
    }
    if (exId === "a1-ex2") {
      const mq = data.MHMQ || {};
      return `Gas: ${mq.gas_detected ? "DETECTED" : "OK"} • Level: ${fmt(mq.level_percent, 0)}%`;
    }
    if (exId === "a1-ex3") {
      const dht = data.DHT11 || {};
      return `Temp: ${fmt(dht.temperature)}°C • Hum: ${fmt(dht.humidity)}%`;
    }
    if (exId === "a1-ex4") {
      const u = data.ULTRASONIC || {};
      const bz = (data.BUZZER || {}).on;
      return `Dist: ${fmt(u.distance_cm)}cm • Buzzer: ${bz ? "ON" : "OFF"}`;
    }
    if (exId === "a1-ex5") {
      const b = data.BMP280 || {};
      return `Temp: ${fmt(b.temperature)}°C • Press: ${fmt(b.pressure, 0)}`;
    }

    if (EX_RUNNER_SET.has(exId)) return "Use Run/Stop";

    return "Ready";
  }

  async function refreshLiveCards() {
    const sensors = await getJSON(API_SENSORS);
    if (!sensors.ok || !sensors.data) return;

    qsa(".exercise-card[data-exercise]").forEach((card) => {
      const exId = card.dataset.exercise;
      if (currentRunningEx && exId === currentRunningEx) return;
      const txt = computeExStatus(exId, sensors.data);
      setStatus(exId, txt);
    });
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

  // Run buttons
  qsa("button.run-btn[data-run]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const exId = btn.dataset.run;

      // ✅ SHIFT => Mode B script
      const useScript = !!e.shiftKey;

      try {
        await startExercise(exId, useScript);
      } catch (err) {
        alert(String(err.message || err));
      }
    });
  });

  // Stop buttons
  qsa("button.stop-btn[data-stop]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      try { await stopExercise(btn.dataset.stop); }
      catch (err) { alert(String(err.message || err)); }
    });
  });

  // Speak buttons
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

  // ---------- init ----------
  qsa(".exercise-card[data-exercise]").forEach((card) => {
    const exId = card.dataset.exercise;
    setStatus(exId, "Ready");
  });

  setBusyUI(null);

  setInterval(() => { syncFocusFromServer().catch(() => {}); }, 500);
  setInterval(() => { refreshLiveCards().catch(() => {}); }, 800);
  setInterval(() => { refreshRunnerStatusIfNeeded().catch(() => {}); }, 900);
})();