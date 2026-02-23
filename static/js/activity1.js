/* activity1.js
   Works with your activity1.html markup:
   - Cards: .exercise-card (tabindex=0, role=button)
   - Run buttons:  button.run-btn[data-run="<exerciseId>"]
   - Speak buttons: button.speak-btn[data-speak="<exerciseId>"]
   - Status: span.status[data-status-for="<exerciseId>"]
   - Modal: #exModal, #modalClose, #modalRunBtn, #modalSpeakBtn,
            #modalTitle, #modalDesc, #modalMeta, #modalImg, #modalImg2
   Backend:
   - POST /api/exercise  { id: "<exerciseId>" }
   - GET  /api/exercise_status?id=<exerciseId>   (optional)
*/

(() => {
  const API_RUN = "/api/exercise";
  const API_STATUS = "/api/exercise_status"; // optional if you have it

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

    // optional: add state class on card
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
  const modalSpeakBtn = qs("#modalSpeakBtn");

  let modalExerciseId = null;

  function openModalFromCard(card) {
    if (!modal) return;
    const exId = card.dataset.exercise || "";
    modalExerciseId = exId;

    // title/desc for modal (use your data-say-title/text if present)
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

    // images (two-image split)
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

    // meta chips (read from .ex-meta spans)
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

    // wire modal buttons
    if (modalRunBtn) modalRunBtn.onclick = () => runExercise(exId);
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

  // close modal events
  if (modalClose) modalClose.addEventListener("click", closeModal);
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  // ---------- run logic ----------
  async function runExercise(exId) {
    if (!exId) return;

    setStatus(exId, "Running...", "state-running");

    const { ok, data, text } = await postJSON(API_RUN, { id: exId });

    if (!ok) {
      setStatus(exId, "Error", "state-error");
      console.warn("Run failed:", exId, data || text);
      return;
    }

    // If backend returns message/status, show it
    const msg =
      (data && (data.status || data.message)) ||
      "Running";
    setStatus(exId, msg, "state-running");

    // If backend supports status endpoint, refresh after a short delay
    // (optional; safe if endpoint missing)
    refreshStatus(exId).catch(() => {});
  }

  async function refreshStatus(exId) {
    // try status endpoint; if not present, silently ignore
    const url = `${API_STATUS}?id=${encodeURIComponent(exId)}`;
    const r = await getJSON(url);
    if (!r.ok) return;

    const s = r.data || {};
    // expected: { state: "idle|running|error|missing", text: "Checking" }
    const txt = s.text || s.status || "Checking";
    const state = (s.state === "running") ? "state-running"
                : (s.state === "error") ? "state-error"
                : (s.state === "missing") ? "state-missing"
                : "";
    setStatus(exId, txt, state);
  }

  // ---------- bind cards ----------
  qsa(".exercise-card").forEach((card) => {
    // card click opens modal (but ignore clicks on buttons)
    card.addEventListener("click", (e) => {
      const target = e.target;
      if (target && (target.closest("button") || target.closest("a"))) return;
      openModalFromCard(card);
    });

    // keyboard open
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openModalFromCard(card);
      }
    });
  });

  // ---------- bind run/speak buttons on cards ----------
  qsa("button.run-btn[data-run]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      runExercise(btn.dataset.run);
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

  // ---------- initial statuses ----------
  // show "Checking" immediately, then try status endpoint
  qsa(".exercise-card[data-exercise]").forEach((card) => {
    const exId = card.dataset.exercise;
    setStatus(exId, "Checking");
    refreshStatus(exId).catch(() => {});
  });

  // optional: refresh statuses every 4s
  // comment this out if you don't want polling
  setInterval(() => {
    qsa(".exercise-card[data-exercise]").forEach((card) => {
      refreshStatus(card.dataset.exercise).catch(() => {});
    });
  }, 4000);
})();