// /static/js/choices.js
(() => {
  const cards = Array.from(document.querySelectorAll(".choice-card"));

  // Tiny "tap" feedback
  cards.forEach((card) => {
    card.addEventListener("pointerdown", () => {
      card.dataset.pressed = "1";
    });
    card.addEventListener("pointerup", () => {
      card.dataset.pressed = "0";
    });
    card.addEventListener("pointercancel", () => {
      card.dataset.pressed = "0";
    });
    card.addEventListener("mouseleave", () => {
      card.dataset.pressed = "0";
    });
  });

  // Keyboard shortcuts:
  // 1 = Activities, 2 = Tools, Esc = back to Welcome
  window.addEventListener("keydown", (e) => {
    if (e.key === "1") {
      window.location.href = "/activityfolder";
    } else if (e.key === "2") {
      window.location.href = "/tools";
    } else if (e.key === "Escape") {
      window.location.href = "/";
    }
  });
})();