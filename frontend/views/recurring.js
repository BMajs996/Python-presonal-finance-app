import { createRecurring, deleteRecurring, listRecurring, updateRecurring } from "../api/recurring.js";
import { bindModalClose, closeModal, openModal } from "../components/modal.js";
import { reportError, toast } from "../components/toast.js";
import { todayIso } from "../utils/dates.js";
import { $ } from "../utils/dom.js";
import { escapeHtml } from "../utils/escape.js";
import { money } from "../utils/money.js";
import { loadReferenceData } from "./reference-data.js";

let recurringCache = [];

export async function loadRecurring() {
  recurringCache = await listRecurring();
  $("recurring-table").innerHTML = recurringCache.length
    ? recurringCache.map((recurring) => `<tr>
        <td>${escapeHtml(recurring.category)}</td>
        <td>${escapeHtml(recurring.description || "")}</td>
        <td>${escapeHtml(recurring.account_name || "Main Account")}</td>
        <td class="${recurring.type}">${recurring.type}</td>
        <td class="amount ${recurring.type}">${money(recurring.amount, recurring.currency)}</td>
        <td>${recurring.frequency}</td>
        <td>${recurring.next_date}</td>
        <td><div class="row-actions">
          <button class="ghost" data-action="edit-recurring" data-id="${recurring.id}">Edit</button>
          <button class="ghost" data-action="delete-recurring" data-id="${recurring.id}">Delete</button>
        </div></td>
      </tr>`).join("")
    : '<tr><td colspan="8">No recurring transactions.</td></tr>';
}

async function openRecurringModal(recurring = null) {
  await loadReferenceData();
  $("recurring-id").value = recurring?.id || "";
  $("recurring-modal-title").textContent = recurring ? "Edit recurring transaction" : "Add recurring transaction";
  $("recurring-date-label").firstChild.textContent = recurring ? "Next date" : "Start date";
  $("recurring-date").value = recurring?.next_date || todayIso();
  $("recurring-type").value = recurring?.type || "expense";
  $("recurring-category").value = recurring?.category || "";
  $("recurring-amount").value = recurring?.amount || "";
  $("recurring-frequency").value = recurring?.frequency || "monthly";
  $("recurring-description").value = recurring?.description || "";
  if (recurring?.account_id) $("recurring-account").value = recurring.account_id;
  openModal("recurring-modal");
}

export function initRecurringView({ refresh }) {
  $("add-recurring-btn").addEventListener("click", () => openRecurringModal().catch(reportError));
  bindModalClose("close-recurring-modal", "recurring-modal");
  $("recurring-table").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const id = Number(button.dataset.id);
    if (button.dataset.action === "edit-recurring") {
      const recurring = recurringCache.find((item) => item.id === id);
      if (recurring) openRecurringModal(recurring).catch(reportError);
      return;
    }
    if (button.dataset.action !== "delete-recurring" || !confirm("Deactivate this recurring transaction?")) return;
    try {
      await deleteRecurring(id);
      toast("Recurring transaction deactivated");
      await refresh();
    } catch (error) {
      reportError(error);
    }
  });
  $("recurring-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = $("recurring-id").value;
    const payload = {
      type: $("recurring-type").value,
      category: $("recurring-category").value,
      amount: Number($("recurring-amount").value),
      frequency: $("recurring-frequency").value,
      description: $("recurring-description").value,
      account_id: Number($("recurring-account").value),
      [id ? "next_date" : "start_date"]: $("recurring-date").value,
    };
    try {
      await (id ? updateRecurring(id, payload) : createRecurring(payload));
      closeModal("recurring-modal");
      toast(id ? "Recurring transaction updated" : "Recurring transaction added");
      await refresh();
    } catch (error) {
      reportError(error);
    }
  });
}
