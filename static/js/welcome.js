// /static/js/welcome.js
// Tap/click ANYWHERE on screen to proceed to choices
(() => {
  function goToChoices() {
    window.location.href = "/choices";
  }

  // Tap or click anywhere on screen
  document.addEventListener("pointerup", goToChoices, { once: true });

  // Keyboard fallback (Enter or Space)
  window.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") goToChoices();
  }, { once: true });

  // Pulse the hint text
  const hint = document.getElementById("tapHint");
  if (hint) {
    hint.style.animation = "tapPulse 1.5s ease-in-out infinite";
  }
})();