import { listReconciliationAccounts, listStatements, getStatement, createStatement, clearEntry, completeStatement, cancelStatement } from "../api/reconciliation.js";
import { reportError, toast } from "../components/toast.js";
import { $ } from "../utils/dom.js";
import { todayIso } from "../utils/dates.js";
import { escapeHtml } from "../utils/escape.js";
import { money } from "../utils/money.js";

let active = null;
let accounts = [];
let requestId = 0;
let busy = false;

function render(statement) {
  active = statement;
  $("reconciliation-detail").classList.toggle("hidden", !statement);
  if (!statement) return;
  $("reconciliation-heading").textContent = statement.account_name + " / " + statement.closing_date;
  $("reconciliation-status").textContent = statement.status === "completed" ? "Completed" : "Draft";
  for (const [id, key] of [
    ["reconciliation-opening", "opening_balance_cents"],
    ["reconciliation-closing", "closing_balance_cents"],
    ["reconciliation-cleared", "cleared_balance_cents"],
    ["reconciliation-difference", "difference_cents"],
  ]) $(id).textContent = money(statement[key] / 100, statement.currency);
  $("reconciliation-difference").classList.toggle("expense", statement.difference_cents !== 0);
  $("reconciliation-complete").disabled = statement.status !== "draft" || statement.difference_cents !== 0;
  $("reconciliation-complete").classList.toggle("hidden", statement.status !== "draft");
  $("reconciliation-cancel").classList.toggle("hidden", statement.status !== "draft");
  $("reconciliation-entry-count").textContent = statement.entries.filter(row => row.cleared).length
    + " / " + statement.entries.length + " cleared";
  $("reconciliation-entries").innerHTML = statement.entries.map(row => `<tr>
    <td><input type="checkbox" aria-label="Cleared ${escapeHtml(row.description || row.label)}"
      data-kind="${row.kind}" data-id="${row.entry_id}" ${row.cleared ? "checked" : ""}
      ${statement.status === "completed" ? "disabled" : ""}></td>
    <td>${escapeHtml(row.date)}</td>
    <td>${escapeHtml(row.description || row.label)}<br><small>${escapeHtml(row.label)}</small></td>
    <td class="amount ${row.amount_cents < 0 ? "expense" : "income"}">${money(row.amount_cents / 100, statement.currency)}</td>
  </tr>`).join("") || '<tr><td colspan="4">No entries.</td></tr>';
}

async function history(accountId, token) {
  const rows = await listStatements(accountId);
  if (token !== requestId) return null;
  $("reconciliation-history").innerHTML = rows.map(row => `<tr>
    <td>${escapeHtml(row.closing_date)}</td><td>${escapeHtml(row.status)}</td>
    <td class="amount">${money(row.closing_balance_cents / 100, accounts.find(a => a.id === accountId)?.currency)}</td>
    <td><button class="ghost" data-statement="${row.id}">${row.status === "draft" ? "Resume" : "View"}</button></td>
  </tr>`).join("") || '<tr><td colspan="4">No statements.</td></tr>';
  $("reconciliation-create").classList.toggle("hidden", rows.some(row => row.status === "draft"));
  $("reconciliation-create").querySelector("button").disabled = !accounts.some(a => a.id === accountId && a.active);
  return rows;
}

export async function loadReconciliation() {
  if (busy) return;
  const token = ++requestId;
  const selected = $("reconciliation-account").value;
  $("reconciliation-body").inert = true;
  $("reconciliation-create").classList.add("hidden");
  $("reconciliation-history").replaceChildren();
  render(null);
  try {
  const loadedAccounts = await listReconciliationAccounts();
  if (token !== requestId) return;
  accounts = loadedAccounts;
  $("reconciliation-account").innerHTML = accounts.map(a =>
    `<option value="${a.id}">${escapeHtml(a.name)}${a.active ? "" : " (inactive)"}</option>`).join("");
  if (accounts.some(a => String(a.id) === selected)) $("reconciliation-account").value = selected;
  const accountId = Number($("reconciliation-account").value);
  render(null);
  const rows = await history(accountId, token);
  const draft = rows?.find(row => row.status === "draft");
  if (draft) {
    const statement = await getStatement(draft.id);
    if (token === requestId) render(statement);
  }
  } finally {
    if (token === requestId) $("reconciliation-body").inert = false;
  }
}

async function mutate(action, message) {
  if (busy) return;
  busy = true;
  const focusedEntry = document.activeElement?.closest("#reconciliation-entries input");
  const focusSelector = focusedEntry
    ? `#reconciliation-entries input[data-kind="${focusedEntry.dataset.kind}"][data-id="${focusedEntry.dataset.id}"]` : null;
  ++requestId;
  $("reconciliation-account").disabled = true;
  $("reconciliation-body").inert = true;
  try {
    const statement = await action();
    render(statement);
    await history(Number($("reconciliation-account").value), requestId);
    if (message) toast(message);
  } catch (error) {
    // Restore checked state after rejected writes; server state stays authoritative.
    if (active) {
      try { render(await getStatement(active.id)); } catch { render(null); }
    }
    reportError(error);
  } finally {
    busy = false;
    $("reconciliation-account").disabled = false;
    $("reconciliation-body").inert = false;
    if (focusSelector) document.querySelector(focusSelector)?.focus({ preventScroll: true });
  }
}

export function initReconciliationView() {
  $("reconciliation-date").value = todayIso();
  $("reconciliation-date").max = todayIso();
  $("reconciliation-account").addEventListener("change", () => loadReconciliation().catch(reportError));
  $("reconciliation-create").addEventListener("submit", event => {
    event.preventDefault();
    mutate(() => createStatement({
      account_id: Number($("reconciliation-account").value),
      closing_date: $("reconciliation-date").value,
      closing_balance: $("reconciliation-balance").value,
    }), "Statement draft created");
  });
  $("reconciliation-entries").addEventListener("change", event => {
    const input = event.target.closest("input[data-id]");
    if (!input || !active) return;
    const ident = active.id;
    mutate(() => clearEntry(ident, {
      kind: input.dataset.kind, entry_id: Number(input.dataset.id), cleared: input.checked,
    }));
  });
  $("reconciliation-history").addEventListener("click", async event => {
    const button = event.target.closest("[data-statement]");
    if (!button || busy) return;
    const token = ++requestId;
    try {
      const statement = await getStatement(Number(button.dataset.statement));
      if (token === requestId) render(statement);
    } catch (error) { if (token === requestId) reportError(error); }
  });
  $("reconciliation-complete").addEventListener("click", () => {
    if (!active || !confirm("Complete this statement? Cleared entries will be locked.")) return;
    const ident = active.id;
    mutate(() => completeStatement(ident), "Statement completed");
  });
  $("reconciliation-cancel").addEventListener("click", () => {
    if (!active || !confirm("Discard this draft and its cleared selections?")) return;
    const ident = active.id;
    mutate(() => cancelStatement(ident), "Draft discarded");
  });
}
