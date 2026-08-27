let balanceChart = null;
let expenseChart = null;
let monthlyChart = null;
let categoryTrendChart = null;
let netWorthChart = null;
let accountsCache = [];
let budgetsCache = [];
let recurringCache = [];
let csvPreviewRows = [];

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
  const titles = { dashboard: "Dashboard", transactions: "Transactions", recurring: "Recurring", budgets: "Budgets", reports: "Reports", accounts: "Accounts", transfers: "Transfers" };
  $("page-title").textContent = titles[view];
  if (view === "transactions") loadTransactions();
  if (view === "recurring") loadRecurring();
  if (view === "budgets") loadBudgets();
  if (view === "reports") loadReports();
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
  recurringCache = rows;
  $("recurring-table").innerHTML = rows.length ? rows.map((r) => `<tr><td>${escapeHtml(r.category)}</td><td>${escapeHtml(r.description || "")}</td><td>${escapeHtml(r.account_name || "Main Account")}</td><td class="${r.type}">${r.type}</td><td class="amount ${r.type}">${money(r.amount)}</td><td>${r.frequency}</td><td>${r.next_date}</td><td><div class="row-actions"><button class="ghost" onclick="editRecurring(${r.id})">Edit</button><button class="ghost" onclick="removeRecurring(${r.id})">Delete</button></div></td></tr>`).join("") : `<tr><td colspan="8">No recurring transactions.</td></tr>`;
}
async function removeRecurring(id) { if (!confirm("Deactivate this recurring transaction?")) return; await api(`/api/recurring/${id}`, { method: "DELETE" }); toast("Recurring transaction deactivated"); await refresh(); }

async function openRecurringModal(recurring = null) {
  await loadCategories();
  $("recurring-id").value = recurring?.id || "";
  $("recurring-modal-title").textContent = recurring ? "Edit recurring transaction" : "Add recurring transaction";
  $("recurring-date-label").firstChild.textContent = recurring ? "Next date" : "Start date";
  $("recurring-date").value = recurring?.next_date || new Date().toISOString().slice(0, 10);
  $("recurring-type").value = recurring?.type || "expense";
  $("recurring-category").value = recurring?.category || "";
  $("recurring-amount").value = recurring?.amount || "";
  $("recurring-frequency").value = recurring?.frequency || "monthly";
  $("recurring-description").value = recurring?.description || "";
  if (recurring?.account_id) $("recurring-account").value = recurring.account_id;
  $("recurring-modal").classList.remove("hidden");
}

function editRecurring(id) {
  const recurring = recurringCache.find((row) => row.id === id);
  if (recurring) openRecurringModal(recurring);
}

async function saveRecurring(event) {
  event.preventDefault();
  const id = $("recurring-id").value;
  const payload = {
    type: $("recurring-type").value,
    category: $("recurring-category").value,
    amount: Number($("recurring-amount").value),
    frequency: $("recurring-frequency").value,
    description: $("recurring-description").value,
    account_id: Number($("recurring-account").value),
  };
  payload[id ? "next_date" : "start_date"] = $("recurring-date").value;
  await api(id ? `/api/recurring/${id}` : "/api/recurring", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
  $("recurring-modal").classList.add("hidden");
  toast(id ? "Recurring transaction updated" : "Recurring transaction added");
  await refresh();
}

async function loadBudgets() { budgetsCache = await api("/api/budgets"); renderBudgets(budgetsCache, $("budgets-full"), true); }
function renderBudgets(budgets, target, cards = false) { if (!budgets.length) { target.innerHTML = "<p>No budgets configured.</p>"; return; } target.innerHTML = budgets.map((b) => cards ? budgetCard(b) : budgetItem(b)).join(""); }
function budgetItem(b) { const cls = b.percentage >= 100 ? "danger" : b.percentage >= 80 ? "warn" : ""; return `<div class="budget-item"><div class="budget-top"><strong>${escapeHtml(b.category)}</strong><span>${money(b.spent)} / ${money(b.monthly_limit)}</span></div><div class="progress"><span class="${cls}" style="width:${Math.min(100, b.percentage)}%"></span></div></div>`; }
function budgetCard(b) { const cls = b.percentage >= 100 ? "danger" : b.percentage >= 80 ? "warn" : ""; return `<div class="budget-card"><div class="budget-top"><strong>${escapeHtml(b.category)}</strong><div class="row-actions"><button class="ghost" onclick="editBudget(${b.id})">Edit</button><button class="ghost" onclick="removeBudget(${b.id})">Delete</button></div></div><p>${money(b.spent)} spent of ${money(b.monthly_limit)}</p><div class="progress"><span class="${cls}" style="width:${Math.min(100, b.percentage)}%"></span></div><small>${b.percentage}% used</small></div>`; }
async function removeBudget(id) { if (!confirm("Delete this budget?")) return; await api(`/api/budgets/${id}`, { method: "DELETE" }); toast("Budget deleted"); await refresh(); }

async function openBudgetModal(budget = null) {
  await loadCategories();
  $("budget-id").value = budget?.id || "";
  $("budget-modal-title").textContent = budget ? "Edit budget" : "Add budget";
  $("budget-category").value = budget?.category || "";
  $("budget-limit").value = budget?.monthly_limit || "";
  $("budget-modal").classList.remove("hidden");
}

function editBudget(id) {
  const budget = budgetsCache.find((row) => row.id === id);
  if (budget) openBudgetModal(budget);
}

async function saveBudget(event) {
  event.preventDefault();
  const id = $("budget-id").value;
  await api(id ? `/api/budgets/${id}` : "/api/budgets", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify({
      category: $("budget-category").value,
      monthly_limit: Number($("budget-limit").value),
    }),
  });
  $("budget-modal").classList.add("hidden");
  toast(id ? "Budget updated" : "Budget saved");
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
  const accountId = Number(row.account_id);
  const account = row.account_id
    ? accountsCache.find((item) => item.id === accountId)
    : accountsCache.find((item) => item.name.toLowerCase() === (accountName || "Main Account").toLowerCase());
  const payload = {
    date: row.date,
    type: row.type.toLowerCase(),
    category: row.category,
    amount: Number(row.amount),
    description: row.description || "",
  };
  if (row.account_id) payload.account_id = accountId;
  else if (account) payload.account_id = account.id;
  return { payload, accountName: account?.name || accountName || "Main Account", accountFound: Boolean(account) };
}

function transactionKey(transaction) {
  return [transaction.date, transaction.type, Number(transaction.amount).toFixed(2), String(transaction.description || "").trim().toLowerCase(), transaction.account_id || "main"].join("|");
}

function validateCsvTransaction(mapped) {
  const errors = [];
  const { payload } = mapped;
  const parsedDate = new Date(`${payload.date}T00:00:00`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(payload.date) || Number.isNaN(parsedDate.getTime()) || parsedDate.toISOString().slice(0, 10) !== payload.date) errors.push("Invalid date");
  if (!["income", "expense"].includes(payload.type)) errors.push("Type must be income or expense");
  if (!payload.category.trim()) errors.push("Category is required");
  if (!Number.isFinite(payload.amount) || payload.amount <= 0) errors.push("Amount must be positive");
  if (!mapped.accountFound) errors.push("Account was not found");
  return errors;
}

async function fetchAllTransactions() {
  const items = [];
  let offset = 0;
  while (true) {
    const data = await api(`/api/transactions?limit=500&offset=${offset}`);
    items.push(...data.items);
    if (items.length >= data.total || data.items.length === 0) return items;
    offset += data.items.length;
  }
}

async function prepareCsvPreview(event) {
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

  const existingKeys = new Set((await fetchAllTransactions()).map(transactionKey));
  const fileKeys = new Set();
  csvPreviewRows = rows.slice(1).map((values, index) => {
    const mapped = rowToTransaction(headers, values);
    const errors = validateCsvTransaction(mapped);
    const key = transactionKey(mapped.payload);
    const duplicate = errors.length === 0 && (existingKeys.has(key) || fileKeys.has(key));
    if (!duplicate && errors.length === 0) fileKeys.add(key);
    return { ...mapped, rowNumber: index + 2, errors, status: errors.length ? "invalid" : duplicate ? "duplicate" : "valid" };
  });
  renderCsvPreview();
  $("csv-preview-modal").classList.remove("hidden");
}

function renderCsvPreview() {
  const counts = { valid: 0, invalid: 0, duplicate: 0 };
  csvPreviewRows.forEach((row) => { counts[row.status] += 1; });
  $("csv-valid-count").textContent = counts.valid;
  $("csv-invalid-count").textContent = counts.invalid;
  $("csv-duplicate-count").textContent = counts.duplicate;
  $("confirm-csv-import-btn").textContent = `Import ${counts.valid} valid row${counts.valid === 1 ? "" : "s"}`;
  $("confirm-csv-import-btn").disabled = counts.valid === 0;
  $("csv-preview-table").innerHTML = csvPreviewRows.map((row) => {
    const detail = row.errors.length ? row.errors.join(", ") : row.status === "duplicate" ? "Matches an existing or earlier CSV row" : "Ready to import";
    return `<tr class="row-${row.status}" title="${escapeAttr(detail)}"><td><span class="status ${row.status}">${row.status}</span></td><td>${escapeHtml(row.payload.date)}</td><td>${escapeHtml(row.accountName)}</td><td>${escapeHtml(row.payload.category)}</td><td>${escapeHtml(row.payload.description)}</td><td>${escapeHtml(row.payload.type)}</td><td class="amount">${Number.isFinite(row.payload.amount) ? money(row.payload.amount) : "Invalid"}</td></tr>`;
  }).join("");
}

function closeCsvPreview() {
  csvPreviewRows = [];
  $("csv-preview-modal").classList.add("hidden");
}

async function confirmCsvImport() {
  const rows = csvPreviewRows.filter((row) => row.status === "valid");
  let imported = 0;
  for (const row of rows) {
    try {
      await api("/api/transactions", { method: "POST", body: JSON.stringify(row.payload) });
      imported += 1;
    } catch (error) {
      row.status = "invalid";
      row.errors = [error.message];
    }
  }
  closeCsvPreview();
  toast(`${imported} transaction${imported === 1 ? "" : "s"} imported`);
  await refresh();
}

async function loadReports() {
  const data = await api(`/api/reports/monthly?months=${encodeURIComponent($("report-months").value)}`);
  $("report-income").textContent = money(data.summary.income);
  $("report-expenses").textContent = money(data.summary.expenses);
  $("report-net").textContent = money(data.summary.net);
  $("report-savings").textContent = `${data.summary.savings_rate}%`;
  renderReportCharts(data);
}

function renderReportCharts(data) {
  const labels = data.months.map((row) => row.month);
  if (monthlyChart) monthlyChart.destroy();
  monthlyChart = new Chart($("monthly-chart"), { type: "bar", data: { labels, datasets: [{ label: "Income", data: data.months.map((row) => row.income), backgroundColor: "#15966d" }, { label: "Expenses", data: data.months.map((row) => row.expenses), backgroundColor: "#d94b58" }] }, options: { responsive: true, scales: { y: { beginAtZero: true, ticks: { callback: (value) => money(value) } } } } });
  if (categoryTrendChart) categoryTrendChart.destroy();
  const colors = ["#3b63f3", "#15966d", "#d94b58", "#e7a62b", "#725ac1"];
  categoryTrendChart = new Chart($("category-trend-chart"), { type: "line", data: { labels, datasets: data.category_trends.map((series, index) => ({ label: series.category, data: series.totals, borderColor: colors[index % colors.length], backgroundColor: colors[index % colors.length], tension: .3 })) }, options: { responsive: true, scales: { y: { beginAtZero: true, ticks: { callback: (value) => money(value) } } } } });
  if (netWorthChart) netWorthChart.destroy();
  netWorthChart = new Chart($("net-worth-chart"), { type: "line", data: { labels, datasets: [{ label: "Balance", data: data.months.map((row) => row.balance), borderColor: "#3b63f3", backgroundColor: "rgba(59, 99, 243, .12)", fill: true, tension: .3 }] }, options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { ticks: { callback: (value) => money(value) } } } } });
}

async function refresh() {
  await Promise.all([loadDashboard(), loadCategories()]);
  const visible = document.querySelector(".view:not(.hidden)")?.id;
  if (visible === "transactions-view") await loadTransactions();
  if (visible === "recurring-view") await loadRecurring();
  if (visible === "budgets-view") await loadBudgets();
  if (visible === "reports-view") await loadReports();
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
$("csv-import-file").addEventListener("change", prepareCsvPreview);
$("close-csv-preview-modal").addEventListener("click", closeCsvPreview);
$("cancel-csv-import-btn").addEventListener("click", closeCsvPreview);
$("confirm-csv-import-btn").addEventListener("click", confirmCsvImport);
$("report-months").addEventListener("change", loadReports);
$("add-account-btn").addEventListener("click", openAccountModal);
$("close-account-modal").addEventListener("click", () => $("account-modal").classList.add("hidden"));
$("account-form").addEventListener("submit", saveAccount);
$("add-transfer-btn").addEventListener("click", openTransferModal);
$("close-transfer-modal").addEventListener("click", () => $("transfer-modal").classList.add("hidden"));
$("transfer-form").addEventListener("submit", saveTransfer);
$("add-recurring-btn").addEventListener("click", () => openRecurringModal());
$("close-recurring-modal").addEventListener("click", () => $("recurring-modal").classList.add("hidden"));
$("recurring-form").addEventListener("submit", saveRecurring);
$("add-budget-btn").addEventListener("click", () => openBudgetModal());
$("close-budget-modal").addEventListener("click", () => $("budget-modal").classList.add("hidden"));
$("budget-form").addEventListener("submit", saveBudget);

refresh().catch((error) => { console.error(error); toast(error.message); });
