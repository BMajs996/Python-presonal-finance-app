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

const viewTitles = {
  dashboard: "Dashboard",
  transactions: "Transactions",
  recurring: "Recurring",
  budgets: "Budgets",
  reports: "Reports",
  accounts: "Accounts",
  transfers: "Transfers",
};

const viewLoaders = {
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
  document.querySelectorAll(".nav-item").forEach((button) =>
    button.classList.toggle("active", button.dataset.view === view));
  $("page-title").textContent = viewTitles[view];
  await viewLoaders[view]?.();
}

async function refresh() {
  await Promise.all([loadDashboard(), loadReferenceData()]);
  const visibleView = document.querySelector(".view:not(.hidden)")?.id.replace("-view", "");
  if (visibleView && visibleView !== "dashboard") await viewLoaders[visibleView]?.();
}

function initNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) =>
    button.addEventListener("click", () => showView(button.dataset.view).catch(reportError)));
  document.querySelectorAll("[data-view-target]").forEach((button) =>
    button.addEventListener("click", () => showView(button.dataset.viewTarget).catch(reportError)));
}

initNavigation();
initDashboardView();
initTransactionsView({ refresh });
initRecurringView({ refresh });
initBudgetsView({ refresh });
initReportsView();
initAccountsView({ refresh });
initTransfersView({ refresh });

refresh().catch(reportError);
