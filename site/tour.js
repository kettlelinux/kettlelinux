// The tour's showcases (index.html [data-tabs]): a row of tab buttons that swaps the panel
// screenshot and its text, like the Quick Access panel it shows. Without this script the first
// tab shows.
for (const box of document.querySelectorAll("[data-tabs]")) {
  const buttons = [...box.querySelectorAll("button[data-tab]")];
  const show = (tab) => {
    for (const b of buttons) b.setAttribute("aria-selected", String(b.dataset.tab === tab));
    for (const el of box.querySelectorAll(".panel-shot, .tab-panel")) el.classList.toggle("active", el.dataset.tab === tab);
  };
  for (const b of buttons) b.addEventListener("click", () => show(b.dataset.tab));
  // arrow keys move along the row, as in the panel
  box.querySelector(".tab-buttons").addEventListener("keydown", (e) => {
    const i = buttons.indexOf(document.activeElement);
    if (i < 0 || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) return;
    const next = buttons[(i + (e.key === "ArrowRight" ? 1 : buttons.length - 1)) % buttons.length];
    next.focus();
    show(next.dataset.tab);
  });
}
