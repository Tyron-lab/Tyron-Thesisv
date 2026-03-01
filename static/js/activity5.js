/* activity5.js — Group 5 + EX24 controls + EX24 terminal
   - Speak/Stop are separate buttons
   - EX24 does NOT run a python script anymore (Execute removed)
*/

(() => {
  const API_STATUS = "/api/exercise_status";
  const API_FOCUS = "/api/focus";

  const API_A5_LATEST = "/api/a5/latest";
  const API_A5_COMMAND = "/api/a5/command";

  const API_EX24_LOGS = "/api/ex24/logs";
  const API_EX24_CLEAR = "/api/ex24/clear";

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

  function getCard(exId) {
    return qs(`.exercise-card[data-exercise="${CSS.escape(exId)}"]`);
  }

  function pulseOk(exId) {
    const card = getCard(exId);
    if (!card) return;
    card.classList.remove("pulse-ok");
    void card.offsetWidth;
    card.classList.add("pulse-ok");
    setTimeout(() => card.classList.remove("pulse-ok"), 750);
  }

  // ────────────────────────────────────────────────
  // Terminal helper
  // ────────────────────────────────────────────────
  const ex24Modal = qs("#ex24Modal");
  const ex24CloseBtn = qs("#ex24CloseBtn");
  const eventTerminal = qs("#eventTerminal");
  const exportCsvBtn = qs("#exportCsvBtn");
  const ex24StopBtn = qs("#ex24StopBtn");

  function terminalAppend(line) {
    if (!eventTerminal) return;
    const cur = eventTerminal.textContent || "";
    const next = cur.endsWith("\n") ? (cur + line + "\n") : (cur + "\n" + line + "\n");
    eventTerminal.textContent = next;
    eventTerminal.scrollTop = eventTerminal.scrollHeight;
  }

  async function sendA5Command(cmd) {
    return await postJSON(API_A5_COMMAND, cmd);
  }

  // ────────────────────────────────────────────────
  // Multi-phone focus lock (kept)
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
    });
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
  // Speak (start) / Stop (cancel)
  // ────────────────────────────────────────────────
  let speakingExId = null;

  function stopSpeakingOnly() {
    try { window.speechSynthesis?.cancel(); } catch {}
    speakingExId = null;
    qsa(".exercise-card.state-speaking").forEach(c => c.classList.remove("state-speaking"));
  }

  function startSpeak(exId, text) {
    try {
      if (!("speechSynthesis" in window)) return;

      stopSpeakingOnly();

      speakingExId = exId;
      const card = getCard(exId);
      card?.classList.add("state-speaking");
      setStatus(exId, "Speaking...");

      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1;
      u.pitch = 1;
      u.lang = "en-US";

      u.onend = () => {
        const c = getCard(exId);
        c?.classList.remove("state-speaking");
        if (speakingExId === exId) {
          speakingExId = null;
          setStatus(exId, "Ready");
          pulseOk(exId);
        }
      };

      u.onerror = () => {
        const c = getCard(exId);
        c?.classList.remove("state-speaking");
        if (speakingExId === exId) {
          speakingExId = null;
          setStatus(exId, "Ready");
        }
      };

      window.speechSynthesis.speak(u);
    } catch {}
  }

  function stopSpeakFor(exId) {
    stopSpeakingOnly();
    setStatus(exId, "Ready");
    pulseOk(exId);
  }

  // ────────────────────────────────────────────────
  // Tools modal
  // ────────────────────────────────────────────────
  const toolsModal = qs("#toolsModal");
  const toolsCloseBtn = qs("#toolsCloseBtn");
  const userCountEl = qs("#userCount");
  const latestEventEl = qs("#latestEvent");
  const lastUpdateEl = qs("#lastUpdate");
  const toolsStopAll = qs("#toolsStopAll");

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

  let toolsTimer = null;

  function renderToolsLatest(latest) {
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

  toolsCloseBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeToolsModal();
  });

  toolsModal?.addEventListener("click", (e) => {
    if (e.target === toolsModal) closeToolsModal();
  });

  toolsStopAll?.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    await sendA5Command({ action: "stop" }).catch(() => {});
    pulseOk("a5-ex21-22");
  });

  // ────────────────────────────────────────────────
  // EX24 modal open/close + log polling
  // ────────────────────────────────────────────────
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

  ex24CloseBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeEx24Modal();
  });

  ex24Modal?.addEventListener("click", (e) => {
    if (e.target === ex24Modal) closeEx24Modal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (ex24Modal?.classList.contains("open")) closeEx24Modal();
    if (toolsModal?.classList.contains("open")) closeToolsModal();
  });

  let ex24LogsTimer = null;
  let lastRenderedLen = 0;

  function startEx24Logs() {
    stopEx24Logs();
    lastRenderedLen = 0;
    pullEx24Logs().catch(() => {});
    ex24LogsTimer = setInterval(() => pullEx24Logs().catch(() => {}), 400);
  }

  function stopEx24Logs() {
    if (ex24LogsTimer) clearInterval(ex24LogsTimer);
    ex24LogsTimer = null;
  }

  async function pullEx24Logs() {
    const r = await getJSON(API_EX24_LOGS);
    if (!r.ok || !r.data || !eventTerminal) return;

    const text = (r.data.text || "").trimEnd() + "\n";
    if (text.length !== lastRenderedLen) {
      eventTerminal.textContent = text || "[INFO] Waiting for events...\n";
      lastRenderedLen = text.length;
      eventTerminal.scrollTop = eventTerminal.scrollHeight;
    }
  }

  exportCsvBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!eventTerminal) return;

    const lines = (eventTerminal.textContent || "").split("\n").filter(Boolean);
    const rows = [["timestamp", "level", "message"]];

    for (const line of lines) {
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

  ex24StopBtn?.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    await postJSON(API_EX24_CLEAR, {}).catch(() => {});
    pulseOk("a5-ex24");
    setStatus("a5-ex24", "Ready");
  });

  // ────────────────────────────────────────────────
  // EX24 command wrapper
  // ────────────────────────────────────────────────
  async function ex24Cmd(payload, pretty) {
    openEx24Modal();
    terminalAppend(`[CMD] ${pretty}`);

    const r = await sendA5Command({ exercise_id: "a5-ex24", ...payload }).catch(() => null);

    if (r && r.ok && r.data && r.data.ok) {
      pulseOk("a5-ex24");
      setStatus("a5-ex24", "OK");
      return true;
    } else {
      const msg = r?.data?.error || r?.text || "Command failed";
      terminalAppend(`[ERR] ${pretty} -> ${String(msg).trim()}`);
      setStatus("a5-ex24", "Error", "state-error");
      return false;
    }
  }

  // Bind EX24 control buttons
  qs("#ctrlBuzzerOn")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "buzzer", state: "on" }, "BUZZER ON"); });
  qs("#ctrlBuzzerOff")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "buzzer", state: "off" }, "BUZZER OFF"); });

  qs("#ctrlLedRed")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "led", color: "red" }, "LED RED"); });
  qs("#ctrlLedGreen")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "led", color: "green" }, "LED GREEN"); });
  qs("#ctrlLedOrange")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "led", color: "orange" }, "LED ORANGE"); });
  qs("#ctrlLedOff")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "led", color: "off" }, "LED OFF"); });

  qs("#ctrlServo0")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "servo", angle: 0 }, "SERVO 0°"); });
  qs("#ctrlServo90")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "servo", angle: 90 }, "SERVO 90°"); });
  qs("#ctrlServo180")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "servo", angle: 180 }, "SERVO 180°"); });

  qs("#ctrlRelay1On")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "relay", ch: 1, state: "on" }, "RELAY CH1 ON"); });
  qs("#ctrlRelay1Off")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "relay", ch: 1, state: "off" }, "RELAY CH1 OFF"); });

  // ✅ NEW: ALL ON
  qs("#ctrlRelayAllOn")?.addEventListener("click", (e) => {
    e.preventDefault();
    ex24Cmd({ action: "relay", ch: "all", state: "on" }, "RELAY ALL ON");
  });

  qs("#ctrlRelayAllOff")?.addEventListener("click", (e) => { e.preventDefault(); ex24Cmd({ action: "relay", ch: "all", state: "off" }, "RELAY ALL OFF"); });

  // Card click opens modals
  qsa(".exercise-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      const target = e.target;
      if (target && (target.closest("button") || target.closest("a"))) return;

      const exId = card.dataset.exercise || "";
      if (exId === "a5-ex24") openEx24Modal();
      else if (exId === "a5-ex21-22") openToolsModal();
    });

    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        card.click();
      }
    });
  });

  // Speak buttons
  qsa("button.speak-btn[data-speak]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const exId = btn.getAttribute("data-speak") || "";
      const card = qs(`.exercise-card[data-exercise="${CSS.escape(exId)}"]`);
      const title = card?.dataset.sayTitle || qs("h3", card || document)?.textContent || "Exercise";
      const text = card?.dataset.sayText || qs(".ex-desc", card || document)?.textContent || "";
      startSpeak(exId, `${title}. ${text}`);
    });
  });

  // Stop-speak buttons
  qsa("button.stop-speak-btn[data-stop-speak]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const exId = btn.getAttribute("data-stop-speak") || "";
      stopSpeakFor(exId);
    });
  });

  // Tools nav button
  qs("#openToolsDash")?.addEventListener("click", (e) => {
    e.preventDefault();
    openToolsModal();
  });

  // Init
  qsa(".exercise-card[data-exercise]").forEach((card) => setStatus(card.dataset.exercise, "Ready"));
  setBusyUI(null);

  setInterval(() => syncFocusFromServer().catch(() => {}), 700);
  setInterval(() => getJSON(API_STATUS).catch(() => {}), 1200);
})();