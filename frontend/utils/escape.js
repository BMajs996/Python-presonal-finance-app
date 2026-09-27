export function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    })[character],
  );
}

export const escapeAttr = escapeHtml;

export function transactionClass(type) {
  return type === "income" || type === "expense" ? type : "";
}
