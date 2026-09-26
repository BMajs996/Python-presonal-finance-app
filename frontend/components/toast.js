import { $ } from "../utils/dom.js";

let hideTimer = null;

export function toast(message, action = null) {
  const element = $("toast");
  element.textContent = message;
  if (action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.textContent = action.label;
    button.addEventListener("click", async () => {
      button.disabled = true;
      clearTimeout(hideTimer);
      try {
        await action.run();
      } catch (error) {
        reportError(error);
      }
    }, { once: true });
    element.append(" ", button);
  }
  element.classList.remove("hidden");
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => element.classList.add("hidden"), action ? 10000 : 2500);
}

export function reportError(error) {
  console.error(error);
  toast(error.message || "Something went wrong");
}
