import { getDashboard } from "../api/dashboard.js";
import { renderDashboardCharts } from "../components/charts.js";
import { renderAccounts, renderBudgets, renderRecentTransactions } from "../components/tables.js";
import { reportError } from "../components/toast.js";
import { $ } from "../utils/dom.js";
import { money, setBaseCurrency } from "../utils/money.js";

export async function loadDashboard() {
  const days = $("dashboard-days").value || "30";
  const data = await getDashboard(days);
  setBaseCurrency(data.currency);
  $("balance").textContent = money(data.balance);
  $("income").textContent = money(data.income);
  $("expenses").textContent = money(data.expenses);
  $("net").textContent = money(data.net);
  $("balance-period-label").textContent = `Last ${days} days`;
  renderDashboardCharts(data);
  renderRecentTransactions(data.recent_transactions, $("recent-transactions"));
  renderBudgets(data.budgets, $("budget-list"));
  renderAccounts(data.accounts || [], $("account-list"));
}

export function initDashboardView() {
  $("dashboard-days").addEventListener("change", () => loadDashboard().catch(reportError));
}
