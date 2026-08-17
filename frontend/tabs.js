(() => {
  const buttons = document.querySelectorAll(".tab-btn");
  const panels = {
    matrixify: document.getElementById("tab-matrixify"),
    direct: document.getElementById("tab-direct"),
  };

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      Object.values(panels).forEach((panel) => {
        panel.classList.remove("active");
        panel.hidden = true;
      });

      const panel = panels[btn.dataset.tab];
      panel.classList.add("active");
      panel.hidden = false;
    });
  });
})();
