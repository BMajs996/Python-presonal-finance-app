import { request } from "./client.js";

export const getDashboard = (days) => request(`/api/dashboard?days=${encodeURIComponent(days)}`);
export const getCategories = () => request("/api/categories");

export const getLedgerPolicy = () => request("/api/ledger-policy");
