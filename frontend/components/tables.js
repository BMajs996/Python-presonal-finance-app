import { escapeHtml } from "../utils/escape.js";
import { money } from "../utils/money.js";

export function renderAccounts(accounts, target) {
  target.innerHTML = accounts.length
    ? accounts.map((account) => `
      <div class="account-card">
        <div>
          <strong>${escapeHtml(account.name)}</strong>
          <small>${escapeHtml(account.type.replace("_", " "))} · ${escapeHtml(account.currency)}</small>
        </div>
        <strong>${money(account.balance, account.currency)}</strong>
      </div>`).join("")
    : "<p>No accounts configured.</p>";
}

export function renderRecentTransactions(items, target) {
  target.innerHTML = items.length
    ? items.map((transaction) => `
      <div class="transaction-row">
        <div class="transaction-main">
          <strong>${escapeHtml(transaction.category)}</strong>
          <small>${escapeHtml(transaction.description || "No description")} · ${escapeHtml(transaction.account_name || "Main Account")} · ${transaction.date}</small>
        </div>
        <div class="transaction-amount ${transaction.type}">${transaction.type === "income" ? "+" : "-"}${money(transaction.amount, transaction.currency)}</div>
      </div>`).join("")
    : "<p>No transactions yet.</p>";
}

function budgetProgress(budget) {
  const className = budget.percentage >= 100 ? "danger" : budget.percentage >= 80 ? "warn" : "";
  return `<div class="progress"><span class="${className}" style="width:${Math.min(100, budget.percentage)}%"></span></div>`;
}

export function renderBudgets(budgets, target, editable = false) {
  if (!budgets.length) {
    target.innerHTML = "<p>No budgets configured.</p>";
    return;
  }
  target.innerHTML = budgets.map((budget) => editable
    ? `<div class="budget-card">
        <div class="budget-top">
          <strong>${escapeHtml(budget.category)}</strong>
          <div class="row-actions">
            <button class="ghost" data-action="edit-budget" data-id="${budget.id}">Edit</button>
            <button class="ghost" data-action="delete-budget" data-id="${budget.id}">Delete</button>
          </div>
        </div>
        <p>${money(budget.spent, budget.currency)} spent of ${money(budget.monthly_limit, budget.currency)}</p>
        ${budgetProgress(budget)}
        <small>${budget.percentage}% used</small>
      </div>`
    : `<div class="budget-item">
        <div class="budget-top"><strong>${escapeHtml(budget.category)}</strong><span>${money(budget.spent, budget.currency)} / ${money(budget.monthly_limit, budget.currency)}</span></div>
        ${budgetProgress(budget)}
      </div>`).join("");
}
