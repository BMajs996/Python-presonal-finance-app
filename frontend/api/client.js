function errorMessage(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || "Invalid value").join(", ");
  return "Request failed";
}

export async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
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
