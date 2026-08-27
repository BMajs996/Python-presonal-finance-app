import { request } from "./client.js";

export const listTransactions = (params = new URLSearchParams()) =>
  request(`/api/transactions?${params}`);

export const createTransaction = (payload) =>
  request("/api/transactions", { method: "POST", body: JSON.stringify(payload) });

export const updateTransaction = (id, payload) =>
  request(`/api/transactions/${id}`, { method: "PUT", body: JSON.stringify(payload) });

export const deleteTransaction = (id) =>
  request(`/api/transactions/${id}`, { method: "DELETE" });
