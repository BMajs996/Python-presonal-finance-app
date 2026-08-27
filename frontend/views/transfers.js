import { createTransfer, deleteTransfer, listTransfers } from "../api/transfers.js";
import { bindModalClose, closeModal, openModal } from "../components/modal.js";
import { reportError, toast } from "../components/toast.js";
import { $ } from "../utils/dom.js";
import { escapeHtml } from "../utils/escape.js";
import { money } from "../utils/money.js";
import { todayIso } from "../utils/dates.js";
import { loadReferenceData } from "./reference-data.js";

export async function loadTransfers() {
  const rows = await listTransfers();
  $("transfer-table").innerHTML = rows.length
    ? rows.map((transfer) => `<tr>
        <td>${transfer.date}</td>
        <td>${escapeHtml(transfer.from_account_name)}</td>
        <td>${escapeHtml(transfer.to_account_name)}</td>
        <td class="amount">${money(transfer.amount, transfer.currency)}</td>
        <td>${escapeHtml(transfer.description || "")}</td>
        <td><button class="ghost" data-action="delete-transfer" data-id="${transfer.id}">Delete</button></td>
      </tr>`).join("")
    : '<tr><td colspan="6">No transfers yet.</td></tr>';
}

async function openTransferModal() {
  await loadReferenceData();
  $("transfer-date").value = todayIso();
  $("transfer-amount").value = "";
  $("transfer-description").value = "";
  openModal("transfer-modal");
}

export function initTransfersView({ refresh }) {
  $("add-transfer-btn").addEventListener("click", () => openTransferModal().catch(reportError));
  bindModalClose("close-transfer-modal", "transfer-modal");
  $("transfer-table").addEventListener("click", async (event) => {
    const button = event.target.closest('[data-action="delete-transfer"]');
    if (!button || !confirm("Delete this transfer?")) return;
    try {
      await deleteTransfer(Number(button.dataset.id));
      toast("Transfer deleted");
      await refresh();
    } catch (error) {
      reportError(error);
    }
  });
  $("transfer-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await createTransfer({
        date: $("transfer-date").value,
        from_account_id: Number($("transfer-from").value),
        to_account_id: Number($("transfer-to").value),
        amount: Number($("transfer-amount").value),
        description: $("transfer-description").value,
      });
      closeModal("transfer-modal");
      toast("Transfer created");
      await refresh();
    } catch (error) {
      reportError(error);
    }
  });
}
