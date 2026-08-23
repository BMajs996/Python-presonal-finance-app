let balanceChart = null;
let expenseChart = null;
let accountsCache = [];

const $ = (id) => document.getElementById(id);
const money = (value) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value || 0));

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  if (!response.ok) {
    let message = "Request failed";
    try { const body = await response.json(); message = body.detail || message; } catch {}
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  setTimeout(() => $("toast").classList.add("hidden"), 2500);
}

function showView(view) {
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  $(`${view}-view`).classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  const titles = { dashboard: "Dashboard", transactions: "Transactions", recurring: "Recurring", budgets: "Budgets", accounts: "Accounts", transfers: "Transfers" };
  $("page-title").textContent = titles[view];
  if (view === "transactions") loadTransactions();
  if (view === "recurring") loadRecurring();
  if (view === "budgets") loadBudgets();
  if (view === "accounts") loadAccounts();
  if (view === "transfers") loadTransfers();
}

async function loadDashboard() {
  const days = $("dashboard-days")?.value || "30";
  const data = await api(`/api/dashboard?days=${encodeURIComponent(days)}`);
  $("balance").textContent = money(data.balance);
  $("income").textContent = money(data.income);
  $("expenses").textContent = money(data.expenses);
  $("net").textContent = money(data.net);
  $("balance-period-label").textContent = `Last ${days} days`;
  renderCharts(data);
  renderRecent(data.recent_transactions);
  renderBudgets(data.budgets, $("budget-list"));
  renderAccounts(data.accounts || [], $("account-list"));
}

function renderCharts(data) {
  const labels = data.balance_history.map((x) => x.date);
  const balances = data.balance_history.map((x) => x.balance);
  if (balanceChart) balanceChart.destroy();
  balanceChart = new Chart($("balance-chart"), { type: "line", data: { labels, datasets: [{ label: "Balance", data: balances, borderWidth: 2, tension: .35, fill: true }] }, options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { ticks: { callback: (v) => money(v) } } } } });
  if (expenseChart) expenseChart.destroy();
  expenseChart = new Chart($("expense-chart"), { type: "doughnut", data: { labels: data.expense_categories.map((x) => x.category), datasets: [{ data: data.expense_categories.map((x) => x.total), borderWidth: 0 }] }, options: { responsive: true, plugins: { legend: { position: "bottom" } } } });
}

function renderRecent(items) {
  $("recent-transactions").innerHTML = items.length ? items.map((t) => `<div class="transaction-row"><div class="transaction-main"><strong>${escapeHtml(t.category)}</strong><small>${escapeHtml(t.description || "No description")} · ${escapeHtml(t.account_name || "Main Account")} · ${t.date}</small></div><div class="transaction-amount ${t.type}">${t.type === "income" ? "+" : "-"}${money(t.amount)}</div></div>`).join("") : "<p>No transactions yet.</p>";
}

function renderAccounts(accounts, target) {
  target.innerHTML = accounts.length ? accounts.map((a) => `<div class="account-card"><div><strong>${escapeHtml(a.name)}</strong><small>${escapeHtml(a.type.replace("_", " "))} · ${escapeHtml(a.currency)}</small></div><strong>${money(a.balance)}</strong></div>`).join("") : "<p>No accounts configured.</p>";
}

async function loadAccounts() {
  const accounts = await api("/api/accounts");
  renderAccounts(accounts, $("accounts-full"));
}

async function loadCategories() {
  const [categories, accounts] = await Promise.all([api("/api/categories"), api("/api/accounts")]);
  accountsCache = accounts;
  $("category-filter").innerHTML = `<option value="">All categories</option>` + categories.map((c) => `<option value="${escapeAttr(c)}">${escapeHtml(c)}</option>`).join("");
  $("category-suggestions").innerHTML = categories.map((c) => `<option value="${escapeAttr(c)}"></option>`).join("");
  $("account-filter").innerHTML = `<option value="">All accounts</option>` + accounts.map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join("");
  [$("form-account"), $("transfer-from"), $("transfer-to"), $("recurring-account")].forEach((select) => {
    if (!select) return;
    select.innerHTML = accounts.map((a) => `<option value="${a.id}">${escapeHtml(a.name)} (${money(a.balance)})</option>`).join("");
  });
}

async function loadTransactions() {
  const params = new URLSearchParams({ search: $("search").value, type: $("type-filter").value, category: $("category-filter").value });
  if ($("account-filter").value) params.set("account_id", $("account-filter").value);
  if ($("date-start-filter").value) params.set("date_start", $("date-start-filter").value);
  if ($("date-end-filter").value) params.set("date_end", $("date-end-filter").value);
  const data = await api(`/api/transactions?${params}`);
  $("transaction-count").textContent = `${data.total} record${data.total === 1 ? "" : "s"}`;
  $("transaction-table").innerHTML = data.items.map((t) => `<tr><td>${t.date}</td><td>${escapeHtml(t.account_name || "Main Account")}</td><td>${escapeHtml(t.category)}</td><td>${escapeHtml(t.description || "")}</td><td class="${t.type}">${t.type}</td><td class="amount ${t.type}">${t.type === "income" ? "+" : "-"}${money(t.amount)}</td><td><button class="ghost" onclick="editTransaction(${t.id})">Edit</button><button class="ghost" onclick="removeTransaction(${t.id})">Delete</button></td></tr>`).join("");
}

function transactionFilterParams() {
  const params = new URLSearchParams({ search: $("search").value, type: $("type-filter").value, category: $("category-filter").value });
  if ($("account-filter").value) params.set("account_id", $("account-filter").value);
  if ($("date-start-filter").value) params.set("date_start", $("date-start-filter").value);
  if ($("date-end-filter").value) params.set("date_end", $("date-end-filter").value);
  return params;
}

async function editTransaction(id) {
  const data = await api(`/api/transactions?limit=500`);
  const t = data.items.find((x) => x.id === id);
  if (!t) return;
  await loadCategories();
  $("modal-title").textContent = "Edit transaction";
  $("transaction-id").value = t.id;
  $("form-date").value = t.date;
  $("form-type").value = t.type;
  $("form-category").value = t.category;
  $("form-amount").value = t.amount;
  $("form-description").value = t.description || "";
  $("form-account").value = t.account_id || "";
  $("modal").classList.remove("hidden");
}

async function removeTransaction(id) { if (!confirm("Delete this transaction?")) return; await api(`/api/transactions/${id}`, { method: "DELETE" }); toast("Transaction deleted"); await refresh(); }

async function openTransactionModal() {
  await loadCategories();
  $("modal-title").textContent = "Add transaction";
  $("transaction-id").value = "";
  $("form-date").value = new Date().toISOString().slice(0, 10);
  $("form-type").value = "expense";
  $("form-category").value = "";
  $("form-amount").value = "";
  $("form-description").value = "";
  $("modal").classList.remove("hidden");
}

async function saveTransaction(event) {
  event.preventDefault();
  const id = $("transaction-id").value;
  const payload = { date: $("form-date").value, type: $("form-type").value, category: $("form-category").value, amount: Number($("form-amount").value), description: $("form-description").value, account_id: Number($("form-account").value) };
  if (id) { await api(`/api/transactions/${id}`, { method: "PUT", body: JSON.stringify(payload) }); toast("Transaction updated"); }
  else { await api("/api/transactions", { method: "POST", body: JSON.stringify(payload) }); toast("Transaction added"); }
  $("modal").classList.add("hidden"); await refresh();
}

async function loadRecurring() {
  const rows = await api("/api/recurring");
  $("recurring-table").innerHTML = rows.length ? rows.map((r) => `<tr><td>${escapeHtml(r.category)}</td><td>${escapeHtml(r.description || "")}</td><td>${escapeHtml(r.account_name || "Main Account")}</td><td class="${r.type}">${r.type}</td><td class="amount ${r.type}">${money(r.amount)}</td><td>${r.frequency}</td><td>${r.next_date}</td><td><button class="ghost" onclick="removeRecurring(${r.id})">Delete</button></td></tr>`).join("") : `<tr><td colspan="8">No recurring transactions.</td></tr>`;
}
async function removeRecurring(id) { if (!confirm("Deactivate this recurring transaction?")) return; await api(`/api/recurring/${id}`, { method: "DELETE" }); toast("Recurring transaction deactivated"); await refresh(); }

async function openRecurringModal() {
  await loadCategories();
  $("recurring-date").value = new Date().toISOString().slice(0, 10);
  $("recurring-type").value = "expense";
  $("recurring-category").value = "";
  $("recurring-amount").value = "";
  $("recurring-frequency").value = "monthly";
  $("recurring-description").value = "";
  $("recurring-modal").classList.remove("hidden");
}

async function saveRecurring(event) {
  event.preventDefault();
  const payload = {
    start_date: $("recurring-date").value,
    type: $("recurring-type").value,
    category: $("recurring-category").value,
    amount: Number($("recurring-amount").value),
    frequency: $("recurring-frequency").value,
    description: $("recurring-description").value,
    account_id: Number($("recurring-account").value),
  };
  await api("/api/recurring", { method: "POST", body: JSON.stringify(payload) });
  $("recurring-modal").classList.add("hidden");
  toast("Recurring transaction added");
  await refresh();
}

async function loadBudgets() { const budgets = await api("/api/budgets"); renderBudgets(budgets, $("budgets-full"), true); }
function renderBudgets(budgets, target, cards = false) { if (!budgets.length) { target.innerHTML = "<p>No budgets configured.</p>"; return; } target.innerHTML = budgets.map((b) => cards ? budgetCard(b) : budgetItem(b)).join(""); }
function budgetItem(b) { const cls = b.percentage >= 100 ? "danger" : b.percentage >= 80 ? "warn" : ""; return `<div class="budget-item"><div class="budget-top"><strong>${escapeHtml(b.category)}</strong><span>${money(b.spent)} / ${money(b.monthly_limit)}</span></div><div class="progress"><span class="${cls}" style="width:${Math.min(100, b.percentage)}%"></span></div></div>`; }
function budgetCard(b) { const cls = b.percentage >= 100 ? "danger" : b.percentage >= 80 ? "warn" : ""; return `<div class="budget-card"><div class="budget-top"><strong>${escapeHtml(b.category)}</strong><button class="ghost" onclick="removeBudget(${b.id})">Delete</button></div><p>${money(b.spent)} spent of ${money(b.monthly_limit)}</p><div class="progress"><span class="${cls}" style="width:${Math.min(100, b.percentage)}%"></span></div><small>${b.percentage}% used</small></div>`; }
async function removeBudget(id) { if (!confirm("Delete this budget?")) return; await api(`/api/budgets/${id}`, { method: "DELETE" }); toast("Budget deleted"); await refresh(); }

async function openBudgetModal() {
  await loadCategories();
  $("budget-category").value = "";
  $("budget-limit").value = "";
  $("budget-modal").classList.remove("hidden");
}

async function saveBudget(event) {
  event.preventDefault();
  await api("/api/budgets", {
    method: "POST",
    body: JSON.stringify({
      category: $("budget-category").value,
      monthly_limit: Number($("budget-limit").value),
    }),
  });
  $("budget-modal").classList.add("hidden");
  toast("Budget saved");
  await refresh();
}

async function loadTransfers() {
  const rows = await api("/api/transfers");
  $("transfer-table").innerHTML = rows.length ? rows.map((t) => `<tr><td>${t.date}</td><td>${escapeHtml(t.from_account_name)}</td><td>${escapeHtml(t.to_account_name)}</td><td class="amount">${money(t.amount)}</td><td>${escapeHtml(t.description || "")}</td><td><button class="ghost" onclick="removeTransfer(${t.id})">Delete</button></td></tr>`).join("") : `<tr><td colspan="6">No transfers yet.</td></tr>`;
}
async function removeTransfer(id) { if (!confirm("Delete this transfer?")) return; await api(`/api/transfers/${id}`, { method: "DELETE" }); toast("Transfer deleted"); await refresh(); }

async function openAccountModal() { $("account-name").value = ""; $("account-type").value = "checking"; $("account-currency").value = "USD"; $("account-opening").value = "0"; $("account-modal").classList.remove("hidden"); }
async function saveAccount(event) { event.preventDefault(); await api("/api/accounts", { method: "POST", body: JSON.stringify({ name: $("account-name").value, type: $("account-type").value, currency: $("account-currency").value, opening_balance: Number($("account-opening").value) }) }); $("account-modal").classList.add("hidden"); toast("Account added"); await refresh(); }
async function openTransferModal() { await loadCategories(); $("transfer-date").value = new Date().toISOString().slice(0, 10); $("transfer-amount").value = ""; $("transfer-description").value = ""; $("transfer-modal").classList.remove("hidden"); }
async function saveTransfer(event) { event.preventDefault(); await api("/api/transfers", { method: "POST", body: JSON.stringify({ date: $("transfer-date").value, from_account_id: Number($("transfer-from").value), to_account_id: Number($("transfer-to").value), amount: Number($("transfer-amount").value), description: $("transfer-description").value }) }); $("transfer-modal").classList.add("hidden"); toast("Transfer created"); await refresh(); }

async function fetchAllTransactionsForExport() {
  const params = transactionFilterParams();
  const items = [];
  let offset = 0;
  while (true) {
    params.set("limit", "500");
    params.set("offset", String(offset));
    const data = await api(`/api/transactions?${params}`);
    items.push(...data.items);
    if (items.length >= data.total || data.items.length === 0) return items;
    offset += data.items.length;
  }
}

function csvValue(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

async function exportTransactionsCsv() {
  const rows = await fetchAllTransactionsForExport();
  const headers = ["date", "type", "category", "amount", "description", "account_id", "account_name"];
  const lines = [headers.join(",")].concat(rows.map((t) => headers.map((key) => csvValue(t[key])).join(",")));
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 10);
  link.href = URL.createObjectURL(blob);
  link.download = `transactions-${stamp}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
  toast(`${rows.length} transaction${rows.length === 1 ? "" : "s"} exported`);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (quoted && char === '"' && next === '"') {
      cell += '"';
      i += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (!quoted && char === ",") {
      row.push(cell);
      cell = "";
    } else if (!quoted && (char === "\n" || char === "\r")) {
      if (char === "\r" && next === "\n") i += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

function rowToTransaction(headers, values) {
  const row = Object.fromEntries(headers.map((header, index) => [header.trim().toLowerCase(), values[index]?.trim() || ""]));
  const accountName = row.account_name || row.account;
  const account = accountName ? accountsCache.find((a) => a.name.toLowerCase() === accountName.toLowerCase()) : null;
  const payload = {
    date: row.date,
    type: row.type.toLowerCase(),
    category: row.category,
    amount: Number(row.amount),
    description: row.description || "",
  };
  if (row.account_id) payload.account_id = Number(row.account_id);
  else if (account) payload.account_id = account.id;
  return payload;
}

async function importTransactionsCsv(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  await loadCategories();
  const text = await file.text();
  const rows = parseCsv(text);
  if (rows.length < 2) {
    toast("CSV must include a header row and at least one transaction");
    return;
  }
  const headers = rows[0].map((header) => header.trim().toLowerCase());
  const required = ["date", "type", "category", "amount"];
  const missing = required.filter((header) => !headers.includes(header));
  if (missing.length) {
    toast(`Missing CSV columns: ${missing.join(", ")}`);
    return;
  }

  let imported = 0;
  for (const values of rows.slice(1)) {
    const payload = rowToTransaction(headers, values);
    await api("/api/transactions", { method: "POST", body: JSON.stringify(payload) });
    imported += 1;
  }
  toast(`${imported} transaction${imported === 1 ? "" : "s"} imported`);
  await refresh();
}

async function refresh() {
  await Promise.all([loadDashboard(), loadCategories()]);
  const visible = document.querySelector(".view:not(.hidden)")?.id;
  if (visible === "transactions-view") await loadTransactions();
  if (visible === "recurring-view") await loadRecurring();
  if (visible === "budgets-view") await loadBudgets();
  if (visible === "accounts-view") await loadAccounts();
  if (visible === "transfers-view") await loadTransfers();
}
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[c])); }
function escapeAttr(value) { return escapeHtml(value); }

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
document.querySelectorAll("[data-view-target]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.viewTarget)));
$("add-transaction-btn").addEventListener("click", openTransactionModal);
$("add-transaction-btn-2").addEventListener("click", openTransactionModal);
$("close-modal").addEventListener("click", () => $("modal").classList.add("hidden"));
$("transaction-form").addEventListener("submit", saveTransaction);
$("filter-btn").addEventListener("click", loadTransactions);
$("dashboard-days").addEventListener("change", loadDashboard);
$("export-csv-btn").addEventListener("click", exportTransactionsCsv);
$("import-csv-btn").addEventListener("click", () => $("csv-import-file").click());
$("csv-import-file").addEventListener("change", importTransactionsCsv);
$("add-account-btn").addEventListener("click", openAccountModal);
$("close-account-modal").addEventListener("click", () => $("account-modal").classList.add("hidden"));
$("account-form").addEventListener("submit", saveAccount);
$("add-transfer-btn").addEventListener("click", openTransferModal);
$("close-transfer-modal").addEventListener("click", () => $("transfer-modal").classList.add("hidden"));
$("transfer-form").addEventListener("submit", saveTransfer);
$("add-recurring-btn").addEventListener("click", openRecurringModal);
$("close-recurring-modal").addEventListener("click", () => $("recurring-modal").classList.add("hidden"));
$("recurring-form").addEventListener("submit", saveRecurring);
$("add-budget-btn").addEventListener("click", openBudgetModal);
$("close-budget-modal").addEventListener("click", () => $("budget-modal").classList.add("hidden"));
$("budget-form").addEventListener("submit", saveBudget);

refresh().catch((error) => { console.error(error); toast(error.message); });
