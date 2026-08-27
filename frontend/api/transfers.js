import { request } from "./client.js";

export const listTransfers = () => request("/api/transfers");
export const createTransfer = (payload) =>
  request("/api/transfers", { method: "POST", body: JSON.stringify(payload) });
export const deleteTransfer = (id) =>
  request(`/api/transfers/${id}`, { method: "DELETE" });
