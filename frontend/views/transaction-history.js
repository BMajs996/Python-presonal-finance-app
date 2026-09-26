import { listDeletedTransactions, restoreTransaction, transactionHistory } from "../api/transactions.js";
import { openModal, closeModal } from "../components/modal.js";
import { reportError, toast } from "../components/toast.js";
import { $ } from "../utils/dom.js";
import { escapeHtml } from "../utils/escape.js";
import { money } from "../utils/money.js";

let deletedOffset = 0;
let historyOffset = 0;
let historyId = null;
let historyRequest = 0;
const returnFocus = new Map();

function openDialog(id) {
  returnFocus.set(id, document.activeElement);
  if (id === "transaction-history-modal") $("deleted-transactions-modal").inert = true;
  openModal(id);
  $(id).querySelector("button").focus();
}

function closeDialog(id) {
  closeModal(id);
  if (id === "transaction-history-modal") $("deleted-transactions-modal").inert = false;
  returnFocus.get(id)?.focus();
  returnFocus.delete(id);
}

async function loadDeleted() {
  const data = await listDeletedTransactions(deletedOffset);
  if (data.items.length === 0 && deletedOffset > 0) {
    deletedOffset = Math.max(0, deletedOffset - 50);
    return loadDeleted();
  }
  $("deleted-count").textContent = `${data.total} deleted transaction${data.total === 1 ? "" : "s"}`;
  $("deleted-previous").disabled = deletedOffset === 0;
  $("deleted-next").disabled = deletedOffset + data.items.length >= data.total;
  $("deleted-table").innerHTML = data.items.length ? data.items.map(row => `<tr>
    <td>${escapeHtml(row.date)}</td>
    <td>${escapeHtml(row.description || row.category)}<br><small>${escapeHtml(row.account_name)}</small></td>
    <td class="amount ${row.type}">${row.type === "income" ? "+" : "-"}${money(row.amount, row.currency)}</td>
    <td><div class="row-actions">
      <button class="ghost" data-history="${row.id}">History</button>
      <button class="ghost" data-restore="${row.id}">Restore</button>
    </div></td>
  </tr>`).join("") : '<tr><td colspan="4">No deleted transactions.</td></tr>';
}

function snapshotValue(snapshot, field) {
  if (!snapshot) return "-";
  if (field === "amount_cents") return money(snapshot[field] / 100, snapshot.currency);
  if (field === "deleted_at") return snapshot[field] ? "Deleted" : "Active";
  return snapshot[field] ?? "";
}

async function loadHistory() {
  const requestId = ++historyRequest;
  const data = await transactionHistory(historyId, historyOffset);
  if (requestId !== historyRequest) return;
  $("history-previous").disabled = historyOffset === 0;
  $("history-next").disabled = historyOffset + data.items.length >= data.total;
  const fields = {
    date: "Date", type: "Type", category: "Category", amount_cents: "Amount",
    account_name: "Account", description: "Description", deleted_at: "Status",
  };
  $("transaction-history-list").innerHTML = data.items.map(event => {
    const rows = Object.entries(fields).filter(([field]) =>
      !event.before_state || event.before_state[field] !== event.after_state[field]);
    return `<li class="history-event">
      <h3>${escapeHtml(event.action)} <time>${escapeHtml(new Date(event.occurred_at).toLocaleString())}</time></h3>
      <div class="table-wrap"><table>
        <thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead>
        <tbody>${rows.map(([field, title]) => `<tr><td>${title}</td>
          <td>${escapeHtml(snapshotValue(event.before_state, field))}</td>
          <td>${escapeHtml(snapshotValue(event.after_state, field))}</td></tr>`).join("")}</tbody>
      </table></div>
    </li>`;
  }).join("") || "<li>No recorded changes.</li>";
}

export async function showTransactionHistory(id) {
  historyId = id;
  historyOffset = 0;
  $("transaction-history-list").replaceChildren();
  openDialog("transaction-history-modal");
  await loadHistory();
}

export function initTransactionHistory({ refresh }) {
  $("deleted-transactions-btn").addEventListener("click", async () => {
    deletedOffset = 0;
    try {
      await loadDeleted();
      openDialog("deleted-transactions-modal");
    } catch (error) { reportError(error); }
  });
  for (const [button, modal] of [
    ["close-deleted-transactions", "deleted-transactions-modal"],
    ["close-transaction-history", "transaction-history-modal"],
  ]) {
    $(button).addEventListener("click", () => closeDialog(modal));
    $(modal).addEventListener("keydown", event => {
      if (event.key === "Escape") { event.stopPropagation(); closeDialog(modal); }
      if (event.key !== "Tab") return;
      const buttons = [...$(modal).querySelectorAll("button:not(:disabled)")];
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    });
  }
  for (const [button, change] of [["deleted-previous", -50], ["deleted-next", 50]]) {
    $(button).addEventListener("click", () => {
      deletedOffset += change;
      loadDeleted().catch(reportError);
    });
  }
  for (const [button, change] of [["history-previous", -50], ["history-next", 50]]) {
    $(button).addEventListener("click", () => {
      historyOffset += change;
      loadHistory().catch(reportError);
    });
  }
  $("deleted-table").addEventListener("click", async event => {
    const historyButton = event.target.closest("[data-history]");
    if (historyButton) {
      showTransactionHistory(Number(historyButton.dataset.history)).catch(reportError);
      return;
    }
    const button = event.target.closest("[data-restore]");
    if (!button) return;
    button.disabled = true;
    try {
      await restoreTransaction(Number(button.dataset.restore));
      await loadDeleted();
      await refresh();
      toast("Transaction restored");
    } catch (error) { reportError(error); }
    finally { button.disabled = false; }
  });
}
