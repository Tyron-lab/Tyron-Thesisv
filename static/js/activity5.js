/* activity5.js — Group 5 (ESP32 + MQTT) + EX24 runner
   Works with your activity5.html (uploaded):
   - Tools modal: #toolsModal, #toolsCloseBtn, #userCount, #latestEvent, #lastUpdate, #toolsStopAll
   - EX24 modal: #ex24Modal, #ex24CloseBtn, #eventTerminal, #exportCsvBtn, #ex24StopBtn
   - EX24 card: data-exercise="a5-ex24" + Execute/Stop/Speak buttons
   - Multi-phone busy lock: /api/focus
   - Exercise runner: /api/exercise , /api/exercise_stop , /api/exercise_status , /api/exercise_logs
   - MQTT latest: /api/a5/latest
*/

(() => {
  const API_RUN = "/api/exercise";
  const API_STOP = "/api/exercise_stop";
  const API_STATUS = "/api/exercise_status";
  const API_LOGS = "/api/exercise_logs";
  const API_FOCUS = "/api/focus";

  const API_A5_LATEST = "/api/a5/latest";
  const API_A5_COMMAND = "/api/a5/command";

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

  function setStatus(exId, text, state = "") {
    const el = qs(`[data-status-for="${CSS.escape(exId)}"]`);
    if (el) el.textContent = text;

    const card = qs(`.exercise-card[data-exercise="${CSS.escape(exId)}"]`);
    if (card) {
      card.classList.remove("state-running", "state-error", "state-missing");
      if (state) card.classList.add(state);
    }
  }

  // ────────────────────────────────────────────────
  // Multi-phone focus lock
  // ────────────────────────────────────────────────
  let currentRunningEx = null;

  function setBusyUI(runningExId) {
    const hasRunning = !!runningExId;

    qsa(".exercise-card[data-exercise]").forEach((card) => {
      const exId = card.dataset.exercise;
      const isThis = hasRunning && exId === runningExId;

      // Lock other cards
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

      // Lock buttons in other cards
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
      currentRunningEx = null;
      setBusyUI(null);
      qsa(".exercise-card[data-exercise]").forEach((card) => {
        setStatus(card.dataset.exercise, "Ready");
      });
      return;
    }

    if (exId && exId !== currentRunningEx) {
      currentRunningEx = exId;
      setBusyUI(currentRunningEx);

      qsa(".exercise-card[data-exercise]").forEach((card) => {
        const id = card.dataset.exercise;
        if (id === currentRunningEx) setStatus(id, "Running...", "state-running");
        else setStatus(id, `BUSY (running: ${currentRunningEx})`);
      });
    }
  }

  // ────────────────────────────────────────────────
  // Speech (optional)
  // ────────────────────────────────────────────────
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

  // ────────────────────────────────────────────────
  // Modals
  // ────────────────────────────────────────────────
  const toolsModal = qs("#toolsModal");
  const toolsCloseBtn = qs("#toolsCloseBtn");
  const userCountEl = qs("#userCount");
  const latestEventEl = qs("#latestEvent");
  const lastUpdateEl = qs("#lastUpdate");
  const toolsStopAll = qs("#toolsStopAll");

  const ex24Modal = qs("#ex24Modal");
  const ex24CloseBtn = qs("#ex24CloseBtn");
  const eventTerminal = qs("#eventTerminal");
  const exportCsvBtn = qs("#exportCsvBtn");
  const ex24StopBtn = qs("#ex24StopBtn");

  function openToolsModal() {
    toolsModal?.classList.add("open");
    toolsModal?.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    startToolsPoll();
  }

  function closeToolsModal() {
    toolsModal?.classList.remove("open");
    toolsModal?.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    stopToolsPoll();
  }

  function openEx24Modal() {
    ex24Modal?.classList.add("open");
    ex24Modal?.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    startEx24Logs();
  }

  function closeEx24Modal() {
    ex24Modal?.classList.remove("open");
    ex24Modal?.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    stopEx24Logs();
  }

  // ✅ FIX: X buttons
  toolsCloseBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeToolsModal();
  });

  ex24CloseBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeEx24Modal();
  });

  // click outside modal card closes
  toolsModal?.addEventListener("click", (e) => {
    if (e.target === toolsModal) closeToolsModal();
  });

  ex24Modal?.addEventListener("click", (e) => {
    if (e.target === ex24Modal) closeEx24Modal();
  });

  // ESC closes
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (ex24Modal?.classList.contains("open")) closeEx24Modal();
    if (toolsModal?.classList.contains("open")) closeToolsModal();
  });

  // ────────────────────────────────────────────────
  // Tools Modal poll (MQTT latest)
  // ────────────────────────────────────────────────
  let toolsTimer = null;

  function renderToolsLatest(latest) {
    // latest: {connected,last_update,payload,raw}
    if (userCountEl) userCountEl.textContent = latest?.connected ? "Online" : "Offline";
    if (latestEventEl) {
      const p = latest?.payload;
      if (p && typeof p === "object") latestEventEl.textContent = JSON.stringify(p);
      else latestEventEl.textContent = latest?.raw || "—";
    }
    if (lastUpdateEl) lastUpdateEl.textContent = latest?.last_update || "—";
  }

  async function pollToolsLatest() {
    const r = await getJSON(API_A5_LATEST);
    if (!r.ok || !r.data) return;
    renderToolsLatest(r.data);
  }

  function startToolsPoll() {
    stopToolsPoll();
    pollToolsLatest().catch(() => {});
    toolsTimer = setInterval(() => pollToolsLatest().catch(() => {}), 700);
  }

  function stopToolsPoll() {
    if (toolsTimer) clearInterval(toolsTimer);
    toolsTimer = null;
  }

  toolsStopAll?.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    // Optional: send a stop command to ESP32 side (if you handle it there)
    await postJSON(API_A5_COMMAND, { action: "stop" }).catch(() => {});
    speak("Stop all monitoring.");
  });

  // ────────────────────────────────────────────────
  // Exercise runner for EX24
  // ────────────────────────────────────────────────
  async function startExercise(exId) {
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

    const { ok, data, text } = await postJSON(API_RUN, { exercise_id: exId });
    if (!ok) {
      const msg = (data && (data.error || data.message)) ? (data.error || data.message) : (text || "Run failed");
      setStatus(exId, "Error", "state-error");
      await setFocus(exId, false);
      currentRunningEx = null;
      setBusyUI(null);
      throw new Error(msg);
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

    await postJSON(API_STOP, {}).catch(() => {});
    await setFocus(exId, false);

    setStatus(exId, "Stopped");
    currentRunningEx = null;
    setBusyUI(null);

    qsa(".exercise-card[data-exercise]").forEach((card) => {
      const id = card.dataset.exercise;
      if (id !== exId) setStatus(id, "Ready");
    });
  }

  async function refreshRunnerStatus() {
    if (!currentRunningEx) return;
    const r = await getJSON(API_STATUS);
    if (!r.ok || !r.data) return;

    const running = !!r.data.running;
    if (!running) {
      const doneId = currentRunningEx;
      await setFocus(doneId, false);
      currentRunningEx = null;
      setBusyUI(null);
      setStatus(doneId, "Finished");

      qsa(".exercise-card[data-exercise]").forEach((card) => {
        const id = card.dataset.exercise;
        if (id !== doneId) setStatus(id, "Ready");
      });
    }
  }

  // ────────────────────────────────────────────────
  // EX24 terminal logs from server
  // ────────────────────────────────────────────────
  let ex24LogsTimer = null;
  let lastRenderedLen = 0;

  function startEx24Logs() {
    stopEx24Logs();
    lastRenderedLen = 0;
    if (eventTerminal) eventTerminal.textContent = "[INFO] Waiting for events...\n";
    pullEx24Logs().catch(() => {});
    ex24LogsTimer = setInterval(() => pullEx24Logs().catch(() => {}), 400);
  }

  function stopEx24Logs() {
    if (ex24LogsTimer) clearInterval(ex24LogsTimer);
    ex24LogsTimer = null;
  }

  async function pullEx24Logs() {
    const r = await getJSON(API_LOGS);
    if (!r.ok || !r.data || !eventTerminal) return;

    const out = (r.data.stdout || "").trimEnd();
    const err = (r.data.stderr || "").trimEnd();

    let combined = "";
    if (out) combined += out + "\n";
    if (err) combined += (out ? "\n" : "") + "[STDERR]\n" + err + "\n";

    if (!combined) combined = "[INFO] Waiting for events...\n";

    // only update if changed a bit
    if (combined.length !== lastRenderedLen) {
      eventTerminal.textContent = combined;
      lastRenderedLen = combined.length;
      eventTerminal.scrollTop = eventTerminal.scrollHeight;
    }
  }

  // Export CSV from current terminal text
  exportCsvBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!eventTerminal) return;

    const lines = (eventTerminal.textContent || "").split("\n").filter(Boolean);
    const rows = [["timestamp", "level", "message"]];

    for (const line of lines) {
      // Format from Exercise24.py: [YYYY-MM-DDTHH:MM:SS] LEVEL: msg
      const m = line.match(/^\[(.+?)\]\s+([A-Z]+):\s+(.*)$/);
      if (m) rows.push([m[1], m[2], m[3]]);
      else rows.push(["", "", line]);
    }

    const csv = rows
      .map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","))
      .join("\n");

    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "ex24_events.csv";
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(a.href);
    a.remove();
  });

  // Stop logging button in EX24 modal (also stops the running exercise)
  ex24StopBtn?.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    await stopExercise("a5-ex24").catch(() => {});
  });

  // ────────────────────────────────────────────────
  // Bind cards + buttons
  // ────────────────────────────────────────────────
  qsa(".exercise-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      const target = e.target;
      if (target && (target.closest("button") || target.closest("a"))) return;

      const exId = card.dataset.exercise || "";
      if (exId === "a5-ex24") {
        openEx24Modal();
      } else {
        // For other cards in Activity 5, just open Tools (since you combine 21-22 there)
        // You can change this behavior if you want different modals later.
        if (exId === "a5-ex21-22") openToolsModal();
      }
    });

    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        card.click();
      }
    });
  });

  // Execute EX24 (run script) + open terminal
  qsa('button.run-btn[data-run="a5-ex24"]').forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      try {
        openEx24Modal();
        await startExercise("a5-ex24");
      } catch (err) {
        alert(String(err?.message || err));
      }
    });
  });

  // Stop buttons (works for EX24)
  qsa("button.stop-btn[data-stop]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      try {
        await stopExercise(btn.dataset.stop);
      } catch (err) {
        alert(String(err?.message || err));
      }
    });
  });

  // Speak button (for Activity 5 we keep it simple)
  qsa("button.speak-btn[data-speak]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const exId = btn.dataset.speak || "";
      const card = qs(`.exercise-card[data-exercise="${CSS.escape(exId)}"]`);
      const title = card?.dataset.sayTitle || qs("h3", card || document)?.textContent || "Exercise";
      const text = card?.dataset.sayText || qs(".ex-desc", card || document)?.textContent || "";
      speak(`${title}. ${text}`);
    });
  });

  // Tools nav button
  qs("#openToolsDash")?.addEventListener("click", (e) => {
    e.preventDefault();
    openToolsModal();
  });

  // Init statuses
  qsa(".exercise-card[data-exercise]").forEach((card) => setStatus(card.dataset.exercise, "Ready"));
  setBusyUI(null);

  setInterval(() => syncFocusFromServer().catch(() => {}), 500);
  setInterval(() => refreshRunnerStatus().catch(() => {}), 900);
})();