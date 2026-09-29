import {
  createTransaction,
  previewImport,
  commitImport,
  deleteTransaction,
  listTransactions,
  updateTransaction,
  restoreTransaction,
} from "../api/transactions.js";
import { bindModalClose, closeModal, openModal } from "../components/modal.js";
import { reportError, toast } from "../components/toast.js";
import { csvText, csvValue, parseCsv } from "../utils/csv.js";
import { getBusinessDate, isIsoDate, todayIso, validateDateRange } from "../utils/dates.js";
import { $ } from "../utils/dom.js";
import { escapeAttr, escapeHtml, transactionClass } from "../utils/escape.js";
import { getBaseCurrency, money } from "../utils/money.js";
import { getAccounts, loadReferenceData } from "./reference-data.js";
import { initTransactionHistory, showTransactionHistory } from "./transaction-history.js";

let transactionsCache = [];
let transactionRequestId = 0;
let csvPreviewRows = [];
let csvBatchId = null;
let importing = false;

function filterParams() {
  validateDateRange($("date-start-filter").value, $("date-end-filter").value);
  const params = new URLSearchParams({
    type: $("type-filter").value,
    category: $("category-filter").value,
  });
  if ($("account-filter").value) params.set("account_id", $("account-filter").value);
  if ($("date-start-filter").value) params.set("date_start", $("date-start-filter").value);
  if ($("date-end-filter").value) params.set("date_end", $("date-end-filter").value);
  return params;
}

export async function loadTransactions() {
  const requestId = ++transactionRequestId;
  let data;
  try {
    data = await listTransactions(filterParams());
  } catch (error) {
    if (requestId !== transactionRequestId) return;
    throw error;
  }
  if (requestId !== transactionRequestId) return;
  transactionsCache = data.items;
  $("transaction-count").textContent = `${data.total} record${data.total === 1 ? "" : "s"}`;
  $("transaction-table").innerHTML = data.items.map((transaction) => `<tr>
    <td>${escapeHtml(transaction.date)}</td>
    <td>${escapeHtml(transaction.account_name || "Main Account")}</td>
    <td>${escapeHtml(transaction.category)}</td>
    <td>${escapeHtml(transaction.description || "")}</td>
    <td class="${transactionClass(transaction.type)}">${escapeHtml(transaction.type)}</td>
    <td class="amount ${transactionClass(transaction.type)}">${transaction.type === "income" ? "+" : "-"}${money(transaction.amount, transaction.currency)}</td>
    <td><div class="row-actions">
      <button class="ghost" data-action="edit-transaction" data-id="${transaction.id}">Edit</button>
      <button class="ghost" data-action="transaction-history" data-id="${transaction.id}">History</button>
      <button class="ghost" data-action="delete-transaction" data-id="${transaction.id}">Delete</button>
    </div></td>
  </tr>`).join("");
}

async function openTransactionModal(transaction = null) {
  await loadReferenceData();
  $("modal-title").textContent = transaction ? "Edit transaction" : "Add transaction";
  $("transaction-id").value = transaction?.id || "";
  $("form-date").max = getBusinessDate();
  $("form-date").value = transaction?.date || getBusinessDate();
  $("form-type").value = transaction?.type || "expense";
  $("form-category").value = transaction?.category || "";
  $("form-amount").value = transaction?.amount || "";
  $("form-description").value = transaction?.description || "";
  if (transaction?.account_id) $("form-account").value = transaction.account_id;
  openModal("modal");
}

async function fetchAll(params = new URLSearchParams()) {
  const items = [];
  let offset = 0;
  while (true) {
    params.set("limit", "500");
    params.set("offset", String(offset));
    const data = await listTransactions(params);
    if (data.total > 10000) throw new Error("Export is limited to 10,000 transactions. Narrow the filters.");
    items.push(...data.items);
    if (items.length >= data.total || data.items.length === 0) return items;
    offset += data.items.length;
  }
}

async function exportCsv() {
  const rows = await fetchAll(filterParams());
  const headers = ["date", "type", "category", "amount", "currency", "description", "account_id", "account_name"];
  const lines = [headers.join(",")].concat(
    rows.map((transaction) => headers.map((key) => {
      if (key === "amount") return csvValue(transaction.money?.version === "decimal-v1"
        ? transaction.money.values.amount : transaction.amount);
      return key === "account_id" ? csvValue(transaction[key]) : csvText(transaction[key]);
    }).join(",")),
  );
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `transactions-${todayIso()}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
  toast(`${rows.length} transaction${rows.length === 1 ? "" : "s"} exported`);
}

function mapCsvRow(headers, values) {
  const row = Object.fromEntries(
    headers.map((header, index) => [header, values[index]?.trim() || ""]),
  );
  const accountName = row.account_name || row.account;
  const accountId = Number(row.account_id);
  const account = row.account_id
    ? getAccounts().find((item) => item.id === accountId)
    : getAccounts().find(
      (item) => item.name.toLowerCase() === (accountName || "Main Account").toLowerCase(),
    );
  const payload = {
    date: row.date,
    type: row.type.toLowerCase(),
    category: row.category,
    amount: Number(row.amount),
    description: row.description || "",
  };
  if (row.account_id) payload.account_id = accountId;
  else if (account) payload.account_id = account.id;
  return {
    payload,
    accountName: account?.name || accountName || "Main Account",
    accountFound: Boolean(account),
    currency: account?.currency || getBaseCurrency(),
  };
}

function validationErrors(mapped) {
  const errors = [];
  const { payload } = mapped;
  if (!isIsoDate(payload.date)) errors.push("Invalid date");
  else if (payload.date > getBusinessDate()) errors.push("Future-dated entries are not allowed");
  if (!["income", "expense"].includes(payload.type)) errors.push("Type must be income or expense");
  if (!payload.category.trim()) errors.push("Category is required");
  if (!Number.isFinite(payload.amount) || payload.amount <= 0) errors.push("Amount must be positive");
  if (payload.category.length > 100) errors.push("Category is too long");
  if (payload.description.length > 500) errors.push("Description is too long");
  if (payload.amount > 1000000000) errors.push("Amount exceeds the supported limit");
  if (Number(payload.amount.toFixed(2)) !== payload.amount) errors.push("Amount must have at most two decimal places");
  if (!mapped.accountFound) errors.push("Account was not found");
  return errors;
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
    const detail = row.errors.length
      ? row.errors.join(", ")
      : row.status === "duplicate" ? "Matches an existing or earlier CSV row" : "Ready to import";
    return `<tr class="row-${row.status}" title="${escapeAttr(detail)}">
      <td><span class="status ${row.status}">${row.status}</span></td>
      <td>${escapeHtml(row.payload.date)}</td>
      <td>${escapeHtml(row.accountName)}</td>
      <td>${escapeHtml(row.payload.category)}</td>
      <td>${escapeHtml(row.payload.description)}</td>
      <td>${escapeHtml(row.payload.type)}</td>
      <td class="amount">${Number.isFinite(row.payload.amount) ? money(row.payload.amount, row.currency) : "Invalid"}</td>
    </tr>`;
  }).join("");
}

function closeCsvPreview() {
  if (importing) return;
  csvPreviewRows = [];
  csvBatchId = null;
  closeModal("csv-preview-modal");
}

async function prepareCsvPreview(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) throw new Error("CSV must be 2 MB or smaller");
  await loadReferenceData();
  const rows = parseCsv(await file.text(), 1001);
  if (rows.length < 2) throw new Error("CSV must include a header row and at least one transaction");
  const headers = rows[0].map((header) => header.trim().toLowerCase());
  const missing = ["date", "type", "category", "amount"].filter((header) => !headers.includes(header));
  if (missing.length) throw new Error(`Missing CSV columns: ${missing.join(", ")}`);

  csvBatchId = crypto.randomUUID();
  csvPreviewRows = rows.slice(1).map((values, index) => {
    const mapped = mapCsvRow(headers, values);
    const errors = validationErrors(mapped);
    return {
      ...mapped,
      rowNumber: index + 2,
      errors,
      status: errors.length ? "invalid" : "valid",
    };
  });
  const candidates = csvPreviewRows.filter(row => row.status === "valid");
  if (candidates.length) {
    const checked = await previewImport(candidates.map(row => row.payload));
    checked.rows.forEach((result, index) => {
      candidates[index].status = result.status;
      candidates[index].errors = result.error ? [result.error] : [];
    });
  }
  renderCsvPreview();
  openModal("csv-preview-modal");
}

async function confirmCsvImport(refresh) {
  if (importing || !csvBatchId) return;
  const rows = csvPreviewRows.filter(row => row.status === "valid");
  if (!rows.length) return;
  importing = true;
  $("csv-preview-modal").inert = true;
  try {
    const result = await commitImport(csvBatchId, rows.map(row => row.payload));
    importing = false;
    closeCsvPreview();
    toast(`${result.imported} imported${result.duplicates ? `, ${result.duplicates} duplicates skipped` : ""}`);
    await refresh();
  } finally {
    importing = false;
    $("csv-preview-modal").inert = false;
  }
}

export function initTransactionsView({ refresh }) {
  initTransactionHistory({ refresh });
  [$("add-transaction-btn"), $("add-transaction-btn-2")].forEach((button) =>
    button.addEventListener("click", () => openTransactionModal().catch(reportError)));
  bindModalClose("close-modal", "modal");
  $("filter-btn").addEventListener("click", () => loadTransactions().catch(reportError));
  ["type-filter", "category-filter", "account-filter"].forEach((id) =>
    $(id).addEventListener("change", () => loadTransactions().catch(reportError)));
  $("transaction-table").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const id = Number(button.dataset.id);
    if (button.dataset.action === "transaction-history") {
      showTransactionHistory(id).catch(reportError);
      return;
    }
    if (button.dataset.action === "edit-transaction") {
      const transaction = transactionsCache.find((item) => item.id === id);
      if (transaction) openTransactionModal(transaction).catch(reportError);
      return;
    }
    if (button.dataset.action !== "delete-transaction" || !confirm("Delete this transaction?")) return;
    try {
      await deleteTransaction(id);
      await refresh();
      toast("Transaction deleted", {
        label: "Undo",
        run: async () => {
          await restoreTransaction(id);
          await refresh();
          toast("Transaction restored");
        },
      });
    } catch (error) {
      reportError(error);
    }
  });
  $("transaction-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = $("transaction-id").value;
    const payload = {
      date: $("form-date").value,
      type: $("form-type").value,
      category: $("form-category").value,
      amount: Number($("form-amount").value),
      description: $("form-description").value,
      account_id: Number($("form-account").value),
    };
    try {
      await (id ? updateTransaction(id, payload) : createTransaction(payload));
      closeModal("modal");
      toast(id ? "Transaction updated" : "Transaction added");
      await refresh();
    } catch (error) {
      reportError(error);
    }
  });
  $("export-csv-btn").addEventListener("click", () => exportCsv().catch(reportError));
  $("import-csv-btn").addEventListener("click", () => $("csv-import-file").click());
  $("csv-import-file").addEventListener("change", (event) => prepareCsvPreview(event).catch(reportError));
  bindModalClose("close-csv-preview-modal", "csv-preview-modal");
  $("cancel-csv-import-btn").addEventListener("click", closeCsvPreview);
  $("confirm-csv-import-btn").addEventListener("click", () => confirmCsvImport(refresh).catch(reportError));
}
