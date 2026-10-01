import { request, setCSRFToken } from "./api/client.js";
import { reportError } from "./components/toast.js";
import { $ } from "./utils/dom.js";
import { initAccountsView, loadAccounts } from "./views/accounts.js";
import { initBudgetsView, loadBudgets } from "./views/budgets.js";
import { initDashboardView, loadDashboard } from "./views/dashboard.js";
import { initRecurringView, loadRecurring } from "./views/recurring.js";
import { loadReferenceData } from "./views/reference-data.js";
import { initReportsView, loadReports } from "./views/reports.js";
import { initTransactionsView, loadTransactions } from "./views/transactions.js";
import { initTransfersView, loadTransfers } from "./views/transfers.js";

import { initReconciliationView, loadReconciliation } from "./views/reconciliation.js";

const viewTitles = {
  reconciliation: "Reconciliation",
  dashboard: "Dashboard",
  transactions: "Transactions",
  recurring: "Recurring",
  budgets: "Budgets",
  reports: "Reports",
  accounts: "Accounts",
  transfers: "Transfers",
};

const viewLoaders = {
  reconciliation: loadReconciliation,
  dashboard: loadDashboard,
  transactions: loadTransactions,
  recurring: loadRecurring,
  budgets: loadBudgets,
  reports: loadReports,
  accounts: loadAccounts,
  transfers: loadTransfers,
};

async function showView(view) {
  document.querySelectorAll(".view").forEach((element) => element.classList.add("hidden"));
  $(`${view}-view`).classList.remove("hidden");
  $("mobile-nav-toggle").setAttribute("aria-expanded", "false");
  document.querySelectorAll(".nav-item").forEach((button) =>
    button.classList.toggle("active", button.dataset.view === view));
  $("page-title").textContent = viewTitles[view];
  document.querySelector(".eyebrow").textContent = view === "dashboard" ? "Financial overview" : "Personal finance";
  await viewLoaders[view]?.();
}

async function refresh() {
  await Promise.all([loadDashboard(), loadReferenceData()]);
  const visibleView = document.querySelector(".view:not(.hidden)")?.id.replace("-view", "");
  if (visibleView && visibleView !== "dashboard") await viewLoaders[visibleView]?.();
}

function initNavigation() {
  $("mobile-nav-toggle").addEventListener("click", () => {
    const button = $("mobile-nav-toggle");
    button.setAttribute("aria-expanded", String(button.getAttribute("aria-expanded") !== "true"));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") $("mobile-nav-toggle").setAttribute("aria-expanded", "false");
  });
  document.querySelectorAll(".nav-item").forEach((button) =>
    button.addEventListener("click", () => showView(button.dataset.view).catch(reportError)));
  document.querySelectorAll("[data-view-target]").forEach((button) =>
    button.addEventListener("click", () => showView(button.dataset.viewTarget).catch(reportError)));
}

initReconciliationView();
initNavigation();
initDashboardView();
initTransactionsView({ refresh });
initRecurringView({ refresh });
initBudgetsView({ refresh });
initReportsView();
initAccountsView({ refresh });
initTransfersView({ refresh });

async function start() {
  const session = await request("/api/auth/session");
  setCSRFToken(session.csrf_token);
  $("logout-btn").addEventListener("click", async () => {
    try {
      await request("/api/auth/logout", { method: "POST" });
      window.location.replace("/login");
    } catch (error) { reportError(error); }
  });
  await refresh();
}
window.addEventListener("pageshow", (event) => { if (event.persisted) window.location.reload(); });
start().catch(reportError);
