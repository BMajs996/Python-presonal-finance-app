import { request } from "./client.js";

export const listAccounts = () => request("/api/accounts");
export const createAccount = (payload) =>
  request("/api/accounts", { method: "POST", body: JSON.stringify(payload) });
