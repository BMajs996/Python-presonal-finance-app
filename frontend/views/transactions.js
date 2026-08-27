import {
  createTransaction,
  deleteTransaction,
  listTransactions,
  updateTransaction,
} from "../api/transactions.js";
import { bindModalClose, closeModal, openModal } from "../components/modal.js";
import { reportError, toast } from "../components/toast.js";
import { csvValue, parseCsv } from "../utils/csv.js";
import { isIsoDate, todayIso, validateDateRange } from "../utils/dates.js";
import { $ } from "../utils/dom.js";
import { escapeAttr, escapeHtml } from "../utils/escape.js";
import { getBaseCurrency, money } from "../utils/money.js";
import { getAccounts, loadReferenceData } from "./reference-data.js";

let transactionsCache = [];
let csvPreviewRows = [];

function filterParams() {
  validateDateRange($("date-start-filter").value, $("date-end-filter").value);
  const params = new URLSearchParams({
    search: $("search").value,
    type: $("type-filter").value,
    category: $("category-filter").value,
  });
  if ($("account-filter").value) params.set("account_id", $("account-filter").value);
  if ($("date-start-filter").value) params.set("date_start", $("date-start-filter").value);
  if ($("date-end-filter").value) params.set("date_end", $("date-end-filter").value);
  return params;
}

export async function loadTransactions() {
  const data = await listTransactions(filterParams());
  transactionsCache = data.items;
  $("transaction-count").textContent = `${data.total} record${data.total === 1 ? "" : "s"}`;
  $("transaction-table").innerHTML = data.items.map((transaction) => `<tr>
    <td>${transaction.date}</td>
    <td>${escapeHtml(transaction.account_name || "Main Account")}</td>
    <td>${escapeHtml(transaction.category)}</td>
    <td>${escapeHtml(transaction.description || "")}</td>
    <td class="${transaction.type}">${transaction.type}</td>
    <td class="amount ${transaction.type}">${transaction.type === "income" ? "+" : "-"}${money(transaction.amount, transaction.currency)}</td>
    <td><div class="row-actions">
      <button class="ghost" data-action="edit-transaction" data-id="${transaction.id}">Edit</button>
      <button class="ghost" data-action="delete-transaction" data-id="${transaction.id}">Delete</button>
    </div></td>
  </tr>`).join("");
}

async function openTransactionModal(transaction = null) {
  await loadReferenceData();
  $("modal-title").textContent = transaction ? "Edit transaction" : "Add transaction";
  $("transaction-id").value = transaction?.id || "";
  $("form-date").value = transaction?.date || todayIso();
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
    items.push(...data.items);
    if (items.length >= data.total || data.items.length === 0) return items;
    offset += data.items.length;
  }
}

async function exportCsv() {
  const rows = await fetchAll(filterParams());
  const headers = ["date", "type", "category", "amount", "currency", "description", "account_id", "account_name"];
  const lines = [headers.join(",")].concat(
    rows.map((transaction) => headers.map((key) => csvValue(transaction[key])).join(",")),
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

function transactionKey(transaction) {
  return [
    transaction.date,
    transaction.type,
    Number(transaction.amount).toFixed(2),
    String(transaction.description || "").trim().toLowerCase(),
    transaction.account_id || "main",
  ].join("|");
}

function validationErrors(mapped) {
  const errors = [];
  const { payload } = mapped;
  if (!isIsoDate(payload.date)) errors.push("Invalid date");
  if (!["income", "expense"].includes(payload.type)) errors.push("Type must be income or expense");
  if (!payload.category.trim()) errors.push("Category is required");
  if (!Number.isFinite(payload.amount) || payload.amount <= 0) errors.push("Amount must be positive");
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
  csvPreviewRows = [];
  closeModal("csv-preview-modal");
}

async function prepareCsvPreview(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  await loadReferenceData();
  const rows = parseCsv(await file.text());
  if (rows.length < 2) throw new Error("CSV must include a header row and at least one transaction");
  const headers = rows[0].map((header) => header.trim().toLowerCase());
  const missing = ["date", "type", "category", "amount"].filter((header) => !headers.includes(header));
  if (missing.length) throw new Error(`Missing CSV columns: ${missing.join(", ")}`);

  const existingKeys = new Set((await fetchAll()).map(transactionKey));
  const fileKeys = new Set();
  csvPreviewRows = rows.slice(1).map((values, index) => {
    const mapped = mapCsvRow(headers, values);
    const errors = validationErrors(mapped);
    const key = transactionKey(mapped.payload);
    const duplicate = errors.length === 0 && (existingKeys.has(key) || fileKeys.has(key));
    if (!duplicate && errors.length === 0) fileKeys.add(key);
    return {
      ...mapped,
      rowNumber: index + 2,
      errors,
      status: errors.length ? "invalid" : duplicate ? "duplicate" : "valid",
    };
  });
  renderCsvPreview();
  openModal("csv-preview-modal");
}

async function confirmCsvImport(refresh) {
  const rows = csvPreviewRows.filter((row) => row.status === "valid");
  let imported = 0;
  for (const row of rows) {
    try {
      await createTransaction(row.payload);
      imported += 1;
    } catch (error) {
      row.status = "invalid";
      row.errors = [error.message];
    }
  }
  const failed = rows.length - imported;
  closeCsvPreview();
  toast(`${imported} imported${failed ? `, ${failed} failed` : ""}`);
  await refresh();
}

export function initTransactionsView({ refresh }) {
  [$("add-transaction-btn"), $("add-transaction-btn-2")].forEach((button) =>
    button.addEventListener("click", () => openTransactionModal().catch(reportError)));
  bindModalClose("close-modal", "modal");
  $("filter-btn").addEventListener("click", () => loadTransactions().catch(reportError));
  $("transaction-table").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const id = Number(button.dataset.id);
    if (button.dataset.action === "edit-transaction") {
      const transaction = transactionsCache.find((item) => item.id === id);
      if (transaction) openTransactionModal(transaction).catch(reportError);
      return;
    }
    if (button.dataset.action !== "delete-transaction" || !confirm("Delete this transaction?")) return;
    try {
      await deleteTransaction(id);
      toast("Transaction deleted");
      await refresh();
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
