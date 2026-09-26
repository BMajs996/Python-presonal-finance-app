import { request } from "./client.js";

export const listStatements = account => request("/api/reconciliations?account_id=" + account);
export const getStatement = id => request("/api/reconciliations/" + id);
export const createStatement = data => request("/api/reconciliations", { method: "POST", body: JSON.stringify(data) });
export const clearEntry = (id, data) => request("/api/reconciliations/" + id + "/entries", { method: "PUT", body: JSON.stringify(data) });
export const completeStatement = id => request("/api/reconciliations/" + id + "/complete", { method: "POST" });
export const cancelStatement = id => request("/api/reconciliations/" + id, { method: "DELETE" });

export const listReconciliationAccounts = () => request("/api/reconciliations/accounts");
