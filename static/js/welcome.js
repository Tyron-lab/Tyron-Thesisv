// /static/js/welcome.js
(() => {
  const startBtn = document.getElementById("startBtn");
  const hint = document.querySelector(".hint");

  // Fill missing button text (your HTML had empty button)
  if (startBtn && !startBtn.textContent.trim()) {
    startBtn.textContent = "Start";
  }

  // Optional hint text
  if (hint && !hint.textContent.trim()) {
    hint.textContent = "Press Enter or click Start";
  }

  function goToChoices() {
    // If your route is /choose, use that.
    // If your route is /choices, change this to "/choices".
    window.location.href = "/choices";
  }

  if (startBtn) {
    startBtn.addEventListener("click", goToChoices);
  }

  // Enter key to start
  window.addEventListener("keydown", (e) => {
    if (e.key === "Enter") goToChoices();
  });
})();