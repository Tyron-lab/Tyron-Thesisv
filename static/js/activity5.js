/* activity5.js — Group 5 only (Custom Module • ESP32 + MQTT)
   Behavior:
   - No Run buttons
   - Speak => acts as Stop (sends POST /api/a5/command {action: "stop"})
   - Tools => opens combined multi-user dashboard (EX21+EX22)
   - Multi-phone busy: uses /api/focus (shared)
   - EX24 terminal: opens on card click, placeholder logs
   - Removes sensor values on cards; relies on scripts + modals
*/

(() => {
  // ✅ keep this for any legacy calls (prevents ReferenceError)
  const API_RUN = "/api/exercise";

  const API_STOP = "/api/exercise_stop"; // Adapted for Group 5 stop
  const API_STATUS = "/api/exercise_status";
  const API_LOGS = "/api/exercise_logs"; // for EX24 terminal
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
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
    return { ok: res.ok, status: res.status, data, text };
  }

  async function getJSON(url) {
    const res = await fetch(url, { method: "GET", cache: "no-store" });
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
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

      // Disable buttons in other cards; allow Stop/Speak on running card
      const btns = qsa("button", card);
      btns.forEach((btn) => {
        const isStop = btn.classList.contains("stop-btn") || btn.hasAttribute("data-stop");
        const isSpeak = btn.classList.contains("speak-btn") || btn.hasAttribute("data-speak");
        const allow = !hasRunning || isThis || (isThis && (isStop || isSpeak));

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

    // Modal buttons lock if modal is on a different exercise
    if (hasRunning && modalExerciseId && modalExerciseId !== runningExId) {
      if (modalSpeakBtn) modalSpeakBtn.disabled = true;
    } else {
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

    // ✅ FIX: when focus is cleared, reset ALL cards to Ready on ALL phones
    if (!running) {
      currentRunningEx = null;
      setBusyUI(null);

      qsa(".exercise-card[data-exercise]").forEach((card) => {
        const id = card.dataset.exercise;
        setStatus(id, "Ready");
      });

      return;
    }

    if (exId && exId !== currentRunningEx) {
      currentRunningEx = exId;
      setBusyUI(currentRunningEx);

      // Show "Running..." only on the focused exercise; others show Busy
      qsa(".exercise-card[data-exercise]").forEach((card) => {
        const id = card.dataset.exercise;
        if (id === currentRunningEx) setStatus(id, "Running...", "state-running");
        else setStatus(id, `BUSY (running: ${currentRunningEx})`);
      });
    }
  }

  // ────────────────────────────────────────────────
  // Speech
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
  // Modal
  // ────────────────────────────────────────────────
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

  // Group 5 Tools Dashboard
  const toolsModal = qs("#toolsModal");
  const toolsCloseBtn = qs("#toolsCloseBtn");

  // EX24 Terminal
  const ex24Modal = qs("#ex24Modal");
  const ex24CloseBtn = qs("#ex24CloseBtn");
  const eventTerminal = qs("#eventTerminal");

  let modalExerciseId = null;

  // A5 EX21 live panel (still allowed in popup only)
  const a5LivePanel = qs("#a5LivePanel");
  const a5Dot = qs("#a5Dot");
  const a5ConnText = qs("#a5ConnText");
  const a5Temp = qs("#a5Temp");
  const a5Motion = qs("#a5Motion");
  const a5Noise = qs("#a5Noise");
  const a5Updated = qs("#a5Updated");
  const a5Raw = qs("#a5Raw");

  // A5 EX22 command panel
  const a5CmdPanel = qs("#a5CmdPanel");
  const a5CmdDot = qs("#a5CmdDot");
  const a5CmdText = qs("#a5CmdText");
  const a5CmdLast = qs("#a5CmdLast");
  const a5CmdRaw = qs("#a5CmdRaw");

  const cmdLightOn = qs("#cmdLightOn");
  const cmdLightOff = qs("#cmdLightOff");
  const cmdGateOpen = qs("#cmdGateOpen");
  const cmdGateClose = qs("#cmdGateClose");
  const cmdLedGreen = qs("#cmdLedGreen");
  const cmdAllOff = qs("#cmdAllOff");

  // A5 EX23 storage panel (optional)
  const a5StorePanel = qs("#a5StorePanel");
  const a5StoreDot = qs("#a5StoreDot");
  const a5StoreText = qs("#a5StoreText");
  const a5StorePath = qs("#a5StorePath");
  const a5StoreLast = qs("#a5StoreLast");
  const a5StoreCount = qs("#a5StoreCount");
  const a5StoreUpdated = qs("#a5StoreUpdated");
  const a5StoreRaw = qs("#a5StoreRaw");

  // ────────────────────────────────────────────────
  // Group 5 specific: Speak as Stop
  // ────────────────────────────────────────────────
  function speakAsStop(exId) {
    stopExercise(exId);
    setStatus(exId, "Stopped via Speak");
    speak("Monitoring stopped.");
  }

  // ────────────────────────────────────────────────
  // Tools Dashboard (combined EX21+EX22)
  // ────────────────────────────────────────────────
  function openToolsModal() {
    toolsModal?.classList.add("open");
    toolsModal?.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    startA5Telemetry();
    startA5Commands();
    startA5StoragePanel();
  }

  function closeToolsModal() {
    toolsModal?.classList.remove("open");
    toolsModal?.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    stopA5Telemetry();
    stopA5Commands();
    stopA5StoragePanel();
  }

  // ────────────────────────────────────────────────
  // EX24 Terminal (execute on open)
  // ────────────────────────────────────────────────
  function openEx24Modal() {
    ex24Modal?.classList.add("open");
    ex24Modal?.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    // Execute EX24 logic (e.g. start logging)
    if (eventTerminal) {
      eventTerminal.textContent = "[INFO] EX24 logging started...\n";
      setTimeout(() => {
        if (!eventTerminal) return;
        eventTerminal.textContent += "[EVENT] Buzzer activated\n[EVENT] LED turned on\n";
      }, 1000);
    }
  }

  function closeEx24Modal() {
    ex24Modal?.classList.remove("open");
    ex24Modal?.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    // Stop EX24 logging
    console.log("EX24 logging stopped");
  }

  // ────────────────────────────────────────────────
  // ✅ FIX: close button bindings for X buttons
  // ────────────────────────────────────────────────
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

  // click outside modal-card closes
  toolsModal?.addEventListener("click", (e) => {
    if (e.target === toolsModal) closeToolsModal();
  });

  ex24Modal?.addEventListener("click", (e) => {
    if (e.target === ex24Modal) closeEx24Modal();
  });

  // ESC closes open modals
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (ex24Modal?.classList.contains("open")) closeEx24Modal();
    if (toolsModal?.classList.contains("open")) closeToolsModal();
  });

  // (Optional) if you also want the main exercise modal X to work:
  modalClose?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    modal?.classList.remove("open");
    modal?.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    modalExerciseId = null;
  });

  modal?.addEventListener("click", (e) => {
    if (e.target === modal) {
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
      modalExerciseId = null;
    }
  });

  // ────────────────────────────────────────────────
  // Exercise start/stop (adapted for Group 5 - no run)
  // ────────────────────────────────────────────────
  async function startExercise(exId) {
    // Group 5: no run logic
    if (exId.startsWith("a5-")) return;

    // Original logic for other groups
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
      const msg =
        data && (data.error || data.message)
          ? data.error || data.message
          : text || "Run failed";
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
  // Bind cards + buttons
  // ────────────────────────────────────────────────
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

  // No Run for Group 5 - skip binding

  qsa("button.stop-btn[data-stop]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await stopExercise(btn.dataset.stop);
      } catch (err) {
        alert(String(err.message || err));
      }
    });
  });

  qsa("button.speak-btn[data-speak]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const exId = btn.dataset.speak;
      if (exId.startsWith("a5-")) {
        speakAsStop(exId);
      } else {
        const card = qs(`.exercise-card[data-exercise="${CSS.escape(exId)}"]`);
        if (!card) return;
        const title = card.dataset.sayTitle || qs("h3", card)?.textContent || "Exercise";
        const text = card.dataset.sayText || qs(".ex-desc", card)?.textContent || "";
        speak(`${title}. ${text}`);
      }
    });
  });

  // Tools Dashboard
  qs("#openToolsDash")?.addEventListener("click", (e) => {
    e.preventDefault();
    openToolsModal();
  });

  // EX24 Terminal
  qsa('.exercise-card[data-exercise="a5-ex24"]').forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      openEx24Modal();
    });
  });

  // Init: no indicators, just Ready
  qsa(".exercise-card[data-exercise]").forEach((card) => {
    setStatus(card.dataset.exercise, "Ready");
  });

  setBusyUI(null);

  setInterval(() => {
    syncFocusFromServer().catch(() => {});
  }, 500);

  setInterval(() => {
    refreshRunnerStatus().catch(() => {});
  }, 900);

  // ────────────────────────────────────────────────
  // NOTE:
  // The functions below are referenced above but must already exist in your file:
  // - openModalFromCard(card)
  // - startA5Telemetry / stopA5Telemetry
  // - startA5Commands  / stopA5Commands
  // - startA5StoragePanel / stopA5StoragePanel
  // If you want, paste your remaining bottom part and I’ll merge it into one single final file.
  // ────────────────────────────────────────────────
})();