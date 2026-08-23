let balanceChart = null;
let expenseChart = null;

const $ = (id) => document.getElementById(id);

const money = (value) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(Number(value || 0));

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = "Request failed";
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {}
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

  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });

  const titles = {
    dashboard: "Dashboard",
    transactions: "Transactions",
    recurring: "Recurring",
    budgets: "Budgets",
  };
  $("page-title").textContent = titles[view];

  if (view === "transactions") loadTransactions();
  if (view === "recurring") loadRecurring();
  if (view === "budgets") loadBudgets();
}

async function loadDashboard() {
  const data = await api("/api/dashboard?days=30");

  $("balance").textContent = money(data.balance);
  $("income").textContent = money(data.income);
  $("expenses").textContent = money(data.expenses);
  $("net").textContent = money(data.net);

  renderCharts(data);
  renderRecent(data.recent_transactions);
  renderBudgets(data.budgets, $("budget-list"));
}

function renderCharts(data) {
  const labels = data.balance_history.map((x) => x.date);
  const balances = data.balance_history.map((x) => x.balance);

  if (balanceChart) balanceChart.destroy();
  balanceChart = new Chart($("balance-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Balance",
        data: balances,
        borderWidth: 2,
        tension: .35,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { ticks: { callback: (v) => money(v) } } },
    },
  });

  if (expenseChart) expenseChart.destroy();
  expenseChart = new Chart($("expense-chart"), {
    type: "doughnut",
    data: {
      labels: data.expense_categories.map((x) => x.category),
      datasets: [{
        data: data.expense_categories.map((x) => x.total),
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { position: "bottom" } },
    },
  });
}

function renderRecent(items) {
  $("recent-transactions").innerHTML = items.length
    ? items.map((t) => `
      <div class="transaction-row">
        <div class="transaction-main">
          <strong>${escapeHtml(t.category)}</strong>
          <small>${escapeHtml(t.description || "No description")} · ${t.date}</small>
        </div>
        <div class="transaction-amount ${t.type}">
          ${t.type === "income" ? "+" : "-"}${money(t.amount)}
        </div>
      </div>
    `).join("")
    : "<p>No transactions yet.</p>";
}

async function loadCategories() {
  const categories = await api("/api/categories");
  $("category-filter").innerHTML =
    `<option value="">All categories</option>` +
    categories.map((c) => `<option value="${escapeAttr(c)}">${escapeHtml(c)}</option>`).join("");
}

async function loadTransactions() {
  const params = new URLSearchParams({
    search: $("search").value,
    type: $("type-filter").value,
    category: $("category-filter").value,
  });

  const data = await api(`/api/transactions?${params}`);
  $("transaction-count").textContent = `${data.total} record${data.total === 1 ? "" : "s"}`;

  $("transaction-table").innerHTML = data.items.map((t) => `
    <tr>
      <td>${t.date}</td>
      <td>${escapeHtml(t.category)}</td>
      <td>${escapeHtml(t.description || "")}</td>
      <td class="${t.type}">${t.type}</td>
      <td class="amount ${t.type}">${t.type === "income" ? "+" : "-"}${money(t.amount)}</td>
      <td>
        <button class="ghost" onclick="editTransaction(${t.id})">Edit</button>
        <button class="ghost" onclick="removeTransaction(${t.id})">Delete</button>
      </td>
    </tr>
  `).join("");
}

async function editTransaction(id) {
  const data = await api(`/api/transactions?limit=500`);
  const t = data.items.find((x) => x.id === id);
  if (!t) return;

  $("modal-title").textContent = "Edit transaction";
  $("transaction-id").value = t.id;
  $("form-date").value = t.date;
  $("form-type").value = t.type;
  $("form-category").value = t.category;
  $("form-amount").value = t.amount;
  $("form-description").value = t.description || "";
  $("modal").classList.remove("hidden");
}

async function removeTransaction(id) {
  if (!confirm("Delete this transaction?")) return;
  await api(`/api/transactions/${id}`, { method: "DELETE" });
  toast("Transaction deleted");
  await refresh();
}

function openTransactionModal() {
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
  const payload = {
    date: $("form-date").value,
    type: $("form-type").value,
    category: $("form-category").value,
    amount: Number($("form-amount").value),
    description: $("form-description").value,
  };

  if (id) {
    await api(`/api/transactions/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    toast("Transaction updated");
  } else {
    await api("/api/transactions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    toast("Transaction added");
  }

  $("modal").classList.add("hidden");
  await refresh();
}

async function loadRecurring() {
  const rows = await api("/api/recurring");
  $("recurring-table").innerHTML = rows.length
    ? rows.map((r) => `
      <tr>
        <td>${escapeHtml(r.category)}</td>
        <td>${escapeHtml(r.description || "")}</td>
        <td class="${r.type}">${r.type}</td>
        <td class="amount ${r.type}">${money(r.amount)}</td>
        <td>${r.frequency}</td>
        <td>${r.next_date}</td>
        <td><button class="ghost" onclick="removeRecurring(${r.id})">Delete</button></td>
      </tr>
    `).join("")
    : `<tr><td colspan="7">No recurring transactions.</td></tr>`;
}

async function removeRecurring(id) {
  if (!confirm("Deactivate this recurring transaction?")) return;
  await api(`/api/recurring/${id}`, { method: "DELETE" });
  toast("Recurring transaction deactivated");
  await loadRecurring();
  await loadDashboard();
}

async function loadBudgets() {
  const budgets = await api("/api/budgets");
  renderBudgets(budgets, $("budgets-full"), true);
}

function renderBudgets(budgets, target, cards = false) {
  if (!budgets.length) {
    target.innerHTML = "<p>No budgets configured.</p>";
    return;
  }

  if (cards) {
    target.innerHTML = budgets.map((b) => budgetCard(b)).join("");
  } else {
    target.innerHTML = budgets.map((b) => budgetItem(b)).join("");
  }
}

function budgetItem(b) {
  const cls = b.percentage >= 100 ? "danger" : b.percentage >= 80 ? "warn" : "";
  const width = Math.min(100, b.percentage);
  return `
    <div class="budget-item">
      <div class="budget-top">
        <strong>${escapeHtml(b.category)}</strong>
        <span>${money(b.spent)} / ${money(b.monthly_limit)}</span>
      </div>
      <div class="progress"><span class="${cls}" style="width:${width}%"></span></div>
    </div>
  `;
}

function budgetCard(b) {
  const cls = b.percentage >= 100 ? "danger" : b.percentage >= 80 ? "warn" : "";
  return `
    <div class="budget-card">
      <div class="budget-top">
        <strong>${escapeHtml(b.category)}</strong>
        <button class="ghost" onclick="removeBudget(${b.id})">Delete</button>
      </div>
      <p>${money(b.spent)} spent of ${money(b.monthly_limit)}</p>
      <div class="progress"><span class="${cls}" style="width:${Math.min(100, b.percentage)}%"></span></div>
      <small>${b.percentage}% used</small>
    </div>
  `;
}

async function removeBudget(id) {
  if (!confirm("Delete this budget?")) return;
  await api(`/api/budgets/${id}`, { method: "DELETE" });
  toast("Budget deleted");
  await refresh();
}

async function refresh() {
  await Promise.all([loadDashboard(), loadCategories()]);
  const visible = document.querySelector(".view:not(.hidden)")?.id;
  if (visible === "transactions-view") await loadTransactions();
  if (visible === "recurring-view") await loadRecurring();
  if (visible === "budgets-view") await loadBudgets();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[c]));
}

function escapeAttr(value) {
  return escapeHtml(value);
}

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

document.querySelectorAll("[data-view-target]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.viewTarget));
});

$("add-transaction-btn").addEventListener("click", openTransactionModal);
$("add-transaction-btn-2").addEventListener("click", openTransactionModal);
$("close-modal").addEventListener("click", () => $("modal").classList.add("hidden"));
$("transaction-form").addEventListener("submit", saveTransaction);
$("filter-btn").addEventListener("click", loadTransactions);

$("add-recurring-btn").addEventListener("click", () =>
  toast("Recurring creation API is ready; the form UI is the next enhancement.")
);
$("add-budget-btn").addEventListener("click", () =>
  toast("Budget creation API is ready; the form UI is the next enhancement.")
);

refresh().catch((error) => {
  console.error(error);
  toast(error.message);
});
