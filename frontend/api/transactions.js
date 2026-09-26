import { request } from "./client.js";

export const listTransactions = (params = new URLSearchParams()) =>
  request(`/api/transactions?${params}`);

export const createTransaction = (payload) =>
  request("/api/transactions", { method: "POST", body: JSON.stringify(payload) });

export const updateTransaction = (id, payload) =>
  request(`/api/transactions/${id}`, { method: "PUT", body: JSON.stringify(payload) });

export const deleteTransaction = (id) =>
  request(`/api/transactions/${id}`, { method: "DELETE" });

export const restoreTransaction = (id) =>
  request(`/api/transactions/${id}/restore`, { method: "POST" });

export const listDeletedTransactions = (offset = 0) =>
  request(`/api/transactions/deleted?limit=50&offset=${offset}`);

export const transactionHistory = (id, offset = 0) =>
  request(`/api/transactions/${id}/history?limit=50&offset=${offset}`);
