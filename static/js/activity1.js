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
*/

(() => {
  const API_RUN = "/api/exercise";
  const API_STOP = "/api/exercise_stop";
  const API_STATUS = "/api/exercise_status";
  const API_LOGS = "/api/exercise_logs";

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
    const res = await fetch(url, { method: "GET" });
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

  let modalExerciseId = null;

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
      // Nothing to stop for that card; keep UI clear & simple
      setStatus(requestedExId, "Ready");
      return;
    }

    // If nothing running, just normalize UI
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