import { listAccounts } from "../api/accounts.js";
import { getCategories } from "../api/dashboard.js";
import { $ } from "../utils/dom.js";
import { escapeAttr, escapeHtml } from "../utils/escape.js";
import { money, setBaseCurrency } from "../utils/money.js";

let accounts = [];

export function getAccounts() {
  return accounts;
}

export async function loadReferenceData() {
  const selectedCategory = $("category-filter").value;
  const selectedAccount = $("account-filter").value;
  const [categories, accountRows] = await Promise.all([getCategories(), listAccounts()]);
  accounts = accountRows;
  const mainAccount = accounts.find((account) => account.name === "Main Account");
  if (mainAccount) setBaseCurrency(mainAccount.currency);

  $("category-filter").innerHTML = `<option value="">All categories</option>${categories
    .map((category) => `<option value="${escapeAttr(category)}">${escapeHtml(category)}</option>`)
    .join("")}`;
  $("category-suggestions").innerHTML = categories
    .map((category) => `<option value="${escapeAttr(category)}"></option>`)
    .join("");
  $("account-filter").innerHTML = `<option value="">All accounts</option>${accounts
    .map((account) => `<option value="${account.id}">${escapeHtml(account.name)}</option>`)
    .join("")}`;

  $("category-filter").value = selectedCategory;
  $("account-filter").value = selectedAccount;
  [$("form-account"), $("transfer-from"), $("transfer-to"), $("recurring-account")]
    .forEach((select) => {
      const selected = select.value;
      select.innerHTML = accounts
        .map((account) => `<option value="${account.id}">${escapeHtml(account.name)} (${money(account.balance, account.currency)})</option>`)
        .join("");
      if (selected) select.value = selected;
    });

  return { categories, accounts };
}
