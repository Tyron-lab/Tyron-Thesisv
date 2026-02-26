/* activity1.js
   Updated for Activity 5 Exercise 23: Local Data Storage panel
   Adds:
   - Storage panel (#a5StorePanel) shown only for a5-ex23
   - Polls /api/exercise_logs while a5-ex23 is running to extract:
       - last saved event line (from stdout)
       - count (how many [EX23] lines)
   No backend changes required.
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

  // ✅ A5 EX23 storage panel nodes (NEW)
  const a5StorePanel   = qs("#a5StorePanel");
  const a5StoreDot     = qs("#a5StoreDot");
  const a5StoreText    = qs("#a5StoreText");
  const a5StorePath    = qs("#a5StorePath");
  const a5StoreLast    = qs("#a5StoreLast");
  const a5StoreCount   = qs("#a5StoreCount");
  const a5StoreUpdated = qs("#a5StoreUpdated");
  const a5StoreRaw     = qs("#a5StoreRaw");

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

  bindCmdButtons();

  // ✅ A5 EX23 storage panel (NEW)
  let a5StoreTimer = null;
  let a5StoreCountNum = 0;
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
    a5StoreCountNum = 0;
    a5StoreLastLine = "";

    if (a5StorePath) a5StorePath.textContent = "activity5/logs/ex23_events.csv + ex23_events.jsonl";
    if (a5StoreLast) a5StoreLast.textContent = "—";
    if (a5StoreCount) a5StoreCount.textContent = "0";
    if (a5StoreUpdated) a5StoreUpdated.textContent = "Last update: —";
    if (a5StoreRaw) a5StoreRaw.textContent = "raw: —";

    if (a5StoreTimer) clearInterval(a5StoreTimer);

    // Poll logs to extract [EX23] lines
    a5StoreTimer = setInterval(async () => {
      try {
        // Only poll when Ex23 is active in modal OR currently running
        const logs = await getJSON(API_LOGS);
        const out = logs?.data?.stdout || "";
        const err = logs?.data?.stderr || "";

        if (err) {
          setStoreState("bad", "Error");
          if (a5StoreRaw) a5StoreRaw.textContent = "raw: " + err.slice(-180);
          return;
        }

        // Count lines that start with [EX23]
        const lines = out.split(/\r?\n/).filter(Boolean);
        const ex23Lines = lines.filter(l => l.includes("[EX23]"));

        a5StoreCountNum = ex23Lines.length;
        const last = ex23Lines.length ? ex23Lines[ex23Lines.length - 1] : "";

        if (a5StoreCount) a5StoreCount.textContent = String(a5StoreCountNum);

        if (last && last !== a5StoreLastLine) {
          a5StoreLastLine = last;
          // Show friendly last line
          if (a5StoreLast) a5StoreLast.textContent = last.replace("[EX23]", "").trim() || last;
          if (a5StoreUpdated) a5StoreUpdated.textContent = "Last update: " + new Date().toLocaleTimeString();
          if (a5StoreRaw) a5StoreRaw.textContent = "raw: " + last;
          setStoreState("ok", "Saving ✅");
        } else {
          // No new lines -> still running
          setStoreState("ok", "Running / Waiting for data…");
        }
      } catch (e) {
        setStoreState("bad", "Offline");
      }
    }, 800);

    // Run once immediately
    (async () => {
      try {
        const logs = await getJSON(API_LOGS);
        const out = logs?.data?.stdout || "";
        const lines = out.split(/\r?\n/).filter(Boolean);
        const ex23Lines = lines.filter(l => l.includes("[EX23]"));
        if (a5StoreCount) a5StoreCount.textContent = String(ex23Lines.length);
        if (ex23Lines.length && a5StoreLast) {
          a5StoreLast.textContent = ex23Lines[ex23Lines.length - 1].replace("[EX23]", "").trim();
        }
      } catch {}
    })();
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

    // Panels per exercise
    if (exId === "a5-ex21") startA5Telemetry();
    else stopA5Telemetry();

    if (exId === "a5-ex22") startA5Commands();
    else stopA5Commands();

    // ✅ NEW: Storage panel for ex23
    if (exId === "a5-ex23") startA5StoragePanel();
    else stopA5StoragePanel();

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
    stopA5StoragePanel();
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

    if (currentRunningEx && currentRunningEx !== exId) {
      await postJSON(API_STOP, {});
      setStatus(currentRunningEx, "Stopped");
      currentRunningEx = null;
    }

    setStatus(exId, "Running...", "state-running");

    const { ok, data, text } = await postJSON(API_RUN, { exercise_id: exId });

    if (!ok) {
      const errMsg = (data && data.error) ? data.error : (text || "Error");
      setStatus(exId, "Error", "state-error");
      console.warn("Run failed:", exId, errMsg);
      return;
    }

    currentRunningEx = exId;
    setStatus(exId, "Running...", "state-running");

    // If Ex23 is running and modal is open on it, ensure storage polling is on
    if (exId === "a5-ex23" && modalExerciseId === "a5-ex23") {
      startA5StoragePanel();
    }
  }

  async function stopExercise(requestedExId = null) {
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

    // Stop storage polling after stop (if modal isn't on ex23, it's already hidden)
    if (modalExerciseId !== "a5-ex23") stopA5StoragePanel();
  }

  async function refreshStatus() {
    const r = await getJSON(API_STATUS);
    if (!r.ok) return;

    const isRunning = !!(r.data && r.data.running);

    if (!isRunning && currentRunningEx) {
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

    if (isRunning && currentRunningEx) {
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

  setInterval(() => {
    refreshStatus().catch(() => {});
  }, 1000);
})();