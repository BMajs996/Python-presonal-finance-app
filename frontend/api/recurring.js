import { request } from "./client.js";

export const listRecurring = () => request("/api/recurring");
export const createRecurring = (payload) =>
  request("/api/recurring", { method: "POST", body: JSON.stringify(payload) });
export const updateRecurring = (id, payload) =>
  request(`/api/recurring/${id}`, { method: "PUT", body: JSON.stringify(payload) });
export const deleteRecurring = (id) =>
  request(`/api/recurring/${id}`, { method: "DELETE" });
