(function () {
  const groups = Array.from(document.querySelectorAll(".menu-group"));
  if (!groups.length) return;

  function closeAll() {
    for (const group of groups) {
      group.classList.remove("open");
      const button = group.querySelector("button[aria-controls]");
      if (button instanceof HTMLButtonElement) {
        button.setAttribute("aria-expanded", "false");
      }
    }
  }

  for (const group of groups) {
    const button = group.querySelector("button[aria-controls]");
    if (!(button instanceof HTMLButtonElement)) continue;

    button.addEventListener("click", (event) => {
      event.preventDefault();
      const willOpen = !group.classList.contains("open");
      closeAll();
      if (willOpen) {
        group.classList.add("open");
        button.setAttribute("aria-expanded", "true");
      }
    });

    const submenuLinks = Array.from(group.querySelectorAll(".submenu-item"));
    for (const link of submenuLinks) {
      link.addEventListener("click", () => closeAll());
    }
  }

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest(".menu-group")) return;
    closeAll();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeAll();
    }
  });
})();
