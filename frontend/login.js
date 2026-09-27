const form = document.getElementById("login-form");
const button = document.getElementById("login-submit");
const error = document.getElementById("login-error");
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  error.textContent = "";
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: form.elements.username.value,
        password: form.elements.password.value,
      }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Unable to sign in");
    form.elements.password.value = "";
    window.location.replace("/");
  } catch (cause) {
    error.textContent = cause.message || "Unable to sign in";
  } finally { button.disabled = false; }
});
