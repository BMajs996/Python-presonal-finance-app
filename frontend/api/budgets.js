import { request } from "./client.js";

export const listBudgets = () => request("/api/budgets");
export const createBudget = (payload) =>
  request("/api/budgets", { method: "POST", body: JSON.stringify(payload) });
export const updateBudget = (id, payload) =>
  request(`/api/budgets/${id}`, { method: "PUT", body: JSON.stringify(payload) });
export const deleteBudget = (id) =>
  request(`/api/budgets/${id}`, { method: "DELETE" });
