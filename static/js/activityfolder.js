// /static/js/activityfolder.js
(() => {
  const cards = Array.from(document.querySelectorAll(".act-card"));

  // Click/tap feedback (optional, nice UX)
  cards.forEach((card) => {
    card.addEventListener("pointerdown", () => (card.dataset.pressed = "1"));
    const clear = () => (card.dataset.pressed = "0");
    card.addEventListener("pointerup", clear);
    card.addEventListener("pointercancel", clear);
    card.addEventListener("mouseleave", clear);
  });

  // Keyboard shortcuts:
  // 1..5 open activities
  // B back to choices
  // T tools
  // H home
  window.addEventListener("keydown", (e) => {
    const k = e.key;

    if (k >= "1" && k <= "5") {
      window.location.href = `/activity${k}`;
      return;
    }
    if (k === "b" || k === "B") window.location.href = "/choices";
    if (k === "t" || k === "T") window.location.href = "/tools";
    if (k === "h" || k === "H" || k === "Escape") window.location.href = "/";
  });
})();