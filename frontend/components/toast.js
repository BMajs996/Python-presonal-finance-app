import { $ } from "../utils/dom.js";

let hideTimer = null;

export function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.classList.remove("hidden");
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => element.classList.add("hidden"), 2500);
}

export function reportError(error) {
  console.error(error);
  toast(error.message || "Something went wrong");
}
