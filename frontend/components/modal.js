import { $ } from "../utils/dom.js";

export function openModal(id) {
  $(id).classList.remove("hidden");
}

export function closeModal(id) {
  $(id).classList.add("hidden");
}

export function bindModalClose(buttonId, modalId) {
  $(buttonId).addEventListener("click", () => closeModal(modalId));
}
