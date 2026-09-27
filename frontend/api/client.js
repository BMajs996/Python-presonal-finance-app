let csrfToken = null;

export function setCSRFToken(value) { csrfToken = value; }

function errorMessage(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || "Invalid value").join(", ");
  return "Request failed";
}

export async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}), ...(options.headers || {}) },
  });
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") window.location.replace("/login");
    let message = "Request failed";
    try {
      const body = await response.json();
      message = errorMessage(body.detail);
    } catch {}
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}
