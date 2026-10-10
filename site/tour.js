// The tour's showcases (index.html [data-tabs]): an ARIA tab list that swaps the panel
// screenshot and its text, like the Quick Access panel it shows. Arrow keys, Home and End move
// along the tabs; only the selected one is in the Tab order. Without this script the first tab
// shows.
for (const box of document.querySelectorAll("[data-tabs]")) {
  const buttons = [...box.querySelectorAll('[role="tab"]')];
  const show = (tab, focus) => {
    for (const b of buttons) {
      const on = b.dataset.tab === tab;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    }
    for (const p of box.querySelectorAll(".tab-panel")) {
      p.classList.toggle("active", p.dataset.tab === tab);
      p.hidden = p.dataset.tab !== tab;
    }
    // the screenshot that shows is described by its alt text; the others are hidden from screen readers
    for (const img of box.querySelectorAll(".panel-shot")) {
      const on = img.dataset.tab === tab;
      img.classList.toggle("active", on);
      if (on) img.removeAttribute("aria-hidden");
      else img.setAttribute("aria-hidden", "true");
    }
  };
  for (const b of buttons) b.addEventListener("click", () => show(b.dataset.tab, false));
  box.querySelector('[role="tablist"]').addEventListener("keydown", (e) => {
    const i = buttons.indexOf(document.activeElement);
    if (i < 0) return;
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: buttons.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    show(buttons[(to + buttons.length) % buttons.length].dataset.tab, true);
  });
}
