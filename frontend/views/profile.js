import { request } from "../api/client.js";
import { reportError, toast } from "../components/toast.js";
import { $ } from "../utils/dom.js";

function date(value) { return new Date(value * 1000).toLocaleString(); }

export async function loadProfile() {
  const [profile, sessions] = await Promise.all([request("/api/auth/profile"), request("/api/auth/sessions")]);
  $("profile-name").value = profile.display_name;
  $("signed-in-name").textContent = profile.display_name || profile.username;
  $("profile-email").value = profile.email || "";
  $("profile-phone").value = profile.phone || "";
  $("profile-identity").textContent = `${profile.username} (${profile.is_admin ? "Administrator" : "Member"})`;
  $("profile-email-state").textContent = profile.email_verified_at ? "Verified" : "Unverified";
  $("profile-phone-state").textContent = profile.phone_verified_at ? "Verified" : "Unverified";
  const table = $("profile-sessions");
  table.replaceChildren();
  for (const session of sessions) {
    const row = document.createElement("tr");
    const values = [session.current ? "Current" : "Other", date(session.created_at), date(session.last_seen), date(session.expires_at)];
    const labels = ["Session", "Created", "Last active", "Expires"];
    for (const [index, value] of values.entries()) {
      const cell = document.createElement("td");
      cell.dataset.label = labels[index];
      cell.textContent = value;
      row.append(cell);
    }
    const cell = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Sign out";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await request(`/api/auth/sessions/${encodeURIComponent(session.session_id)}`, { method: "DELETE" });
        if (session.current) window.location.replace("/login");
        else await loadProfile();
      } catch (error) { reportError(error); button.disabled = false; }
    });
    cell.append(button);
    row.append(cell);
    table.append(row);
  }
}

export function initProfileView() {
  $("profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      await request("/api/auth/profile", { method: "PUT", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
      form.elements.current_password.value = "";
      await loadProfile();
      toast("Profile saved");
    } catch (error) { reportError(error); }
    finally { button.disabled = false; }
  });
  $("password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (form.elements.password.value !== form.elements.confirmation.value) {
      toast("Passwords do not match");
      return;
    }
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      await request("/api/auth/password", { method: "POST", body: JSON.stringify({
        current_password: form.elements.current_password.value, password: form.elements.password.value,
      }) });
      form.reset();
      window.location.replace("/login");
    } catch (error) { reportError(error); }
    finally { button.disabled = false; }
  });
  $("revoke-other-sessions").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await request("/api/auth/sessions/revoke-others", { method: "POST" });
      await loadProfile();
    } catch (error) { reportError(error); }
    finally { button.disabled = false; }
  });
}
