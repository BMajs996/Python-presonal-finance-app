import { getDashboard } from "../api/dashboard.js";
import { renderDashboardCharts } from "../components/charts.js";
import { renderAccounts, renderBudgets, renderRecentTransactions } from "../components/tables.js";
import { reportError } from "../components/toast.js";
import { $ } from "../utils/dom.js";
import { money, setBaseCurrency } from "../utils/money.js";

function periodLabel(period) {
  const formatter = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
  const start = formatter.format(new Date(`${period.start}T00:00:00`));
  const end = formatter.format(new Date(`${period.end}T00:00:00`));
  return `${start} - ${end}`;
}

function renderComparison(id, value, inverse = false) {
  const element = $(id);
  if (value === null || value === undefined) {
    element.textContent = "No prior activity";
    element.className = "metric-change neutral";
    return;
  }

  const improved = inverse ? value <= 0 : value >= 0;
  element.textContent = `${value > 0 ? "+" : ""}${value.toLocaleString(undefined, {
    maximumFractionDigits: 1,
  })}% vs prior period`;
  element.className = `metric-change ${improved ? "positive" : "negative"}`;
}

export async function loadDashboard() {
  const days = $("dashboard-days").value || "30";
  const data = await getDashboard(days);
  setBaseCurrency(data.currency);
  $("balance").textContent = money(data.balance);
  $("income").textContent = money(data.income);
  $("expenses").textContent = money(data.expenses);
  $("net").textContent = money(data.net);
  const range = periodLabel(data.period);
  $("balance-period-label").textContent = `Daily balance · ${range}`;
  $("expense-period-label").textContent = range;
  $("balance-context").textContent = `${data.accounts.length} active ${data.accounts.length === 1 ? "account" : "accounts"}`;
  $("income-context").textContent = range;
  $("expenses-context").textContent = range;
  $("net-context").textContent = `${data.savings_rate.toLocaleString(undefined, {
    maximumFractionDigits: 1,
  })}% savings rate`;
  renderComparison("income-change", data.comparison.income);
  renderComparison("expenses-change", data.comparison.expenses, true);
  renderComparison("net-change", data.comparison.net);
  renderDashboardCharts(data);
  renderRecentTransactions(data.recent_transactions, $("recent-transactions"));
  renderBudgets(data.budgets, $("budget-list"));
  renderAccounts(data.accounts || [], $("account-list"));
}

export function initDashboardView() {
  $("dashboard-days").addEventListener("change", () => loadDashboard().catch(reportError));
}
