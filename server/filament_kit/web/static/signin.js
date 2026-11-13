// The sign-in page's Show / Hide passphrase button (04 11.2, 02 5.3). The page is rendered by the Hub with no other
// script; without this file the field stays a plain password field and the button stays hidden.
"use strict";
(() => {
  const btn = document.querySelector(".field__action"), input = btn && document.getElementById(btn.getAttribute("aria-controls"));
  if (!btn || !input) return;
  const set = (shown) => {
    input.type = shown ? "text" : "password";
    btn.setAttribute("aria-pressed", String(shown));
    btn.textContent = btn.dataset[shown ? "hide" : "show"];
    btn.setAttribute("aria-label", btn.dataset[shown ? "hideName" : "showName"]);
  };
  btn.hidden = false;
  set(false);
  btn.addEventListener("click", () => set(input.type === "password"));
  btn.closest(".field__box").addEventListener("focusout", (e) => {
    if (!btn.closest(".field__box").contains(e.relatedTarget)) set(false);
  });
})();
