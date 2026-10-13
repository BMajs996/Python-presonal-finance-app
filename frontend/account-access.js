const form = document.getElementById("account-form");
const button = document.getElementById("account-submit");
const error = document.getElementById("account-error");
const validToken = (value) => /^[A-Za-z0-9_-]{43}$/.test(value || "");
const fragmentToken = new URLSearchParams(window.location.hash.slice(1)).get("token");
const token = validToken(fragmentToken) ? fragmentToken : null;
const invitation = form.elements.invitation;
// Remove the credential from the current history entry; keep it in memory only.
window.history.replaceState(null, "", window.location.pathname);
if (token && invitation) {
  invitation.required = false;
  invitation.classList.add("hidden");
  document.getElementById("invitation-label").classList.add("hidden");
}
if (!token && !invitation) {
  button.disabled = true;
  error.textContent = "A valid account link is required.";
}
function invitationToken() {
  const value = invitation?.value.trim();
  if (validToken(value)) return value;
  try {
    const url = new URL(value);
    const candidate = new URLSearchParams(url.hash.slice(1)).get("token");
    if (url.origin === window.location.origin && url.pathname === "/register" && validToken(candidate)) {
      return candidate;
    }
  } catch { /* Invalid links are rejected before making a request. */ }
  return null;
}
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  const submittedToken = token || invitationToken();
  if (!submittedToken) {
    error.textContent = "A valid account link is required.";
    return;
  }
  if (form.elements.password.value !== form.elements.confirmation.value) {
    error.textContent = "Passwords do not match.";
    return;
  }
  button.disabled = true;
  try {
    const payload = { token: submittedToken, password: form.elements.password.value };
    if (form.dataset.action === "register") {
      for (const key of ["display_name", "username", "email", "phone"]) {
        payload[key] = form.elements[key].value.trim();
      }
    }
    const response = await fetch(`/api/auth/${form.dataset.action}`, {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(typeof body.detail === "string" ? body.detail : "Check the account details and try again.");
    }
    form.reset();
    window.location.replace("/login");
  } catch (cause) {
    error.textContent = cause.message || "Unable to update the account.";
  } finally { button.disabled = !token && !invitation; }
});
window.addEventListener("pageshow", (event) => { if (event.persisted) window.location.reload(); });
