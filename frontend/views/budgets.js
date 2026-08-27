import { createBudget, deleteBudget, listBudgets, updateBudget } from "../api/budgets.js";
import { bindModalClose, closeModal, openModal } from "../components/modal.js";
import { renderBudgets } from "../components/tables.js";
import { reportError, toast } from "../components/toast.js";
import { $ } from "../utils/dom.js";
import { loadReferenceData } from "./reference-data.js";

let budgetsCache = [];

export async function loadBudgets() {
  budgetsCache = await listBudgets();
  renderBudgets(budgetsCache, $("budgets-full"), true);
}

async function openBudgetModal(budget = null) {
  await loadReferenceData();
  $("budget-id").value = budget?.id || "";
  $("budget-modal-title").textContent = budget ? "Edit budget" : "Add budget";
  $("budget-category").value = budget?.category || "";
  $("budget-limit").value = budget?.monthly_limit || "";
  openModal("budget-modal");
}

export function initBudgetsView({ refresh }) {
  $("add-budget-btn").addEventListener("click", () => openBudgetModal().catch(reportError));
  bindModalClose("close-budget-modal", "budget-modal");
  $("budgets-full").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const id = Number(button.dataset.id);
    if (button.dataset.action === "edit-budget") {
      const budget = budgetsCache.find((item) => item.id === id);
      if (budget) openBudgetModal(budget).catch(reportError);
      return;
    }
    if (button.dataset.action !== "delete-budget" || !confirm("Delete this budget?")) return;
    try {
      await deleteBudget(id);
      toast("Budget deleted");
      await refresh();
    } catch (error) {
      reportError(error);
    }
  });
  $("budget-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = $("budget-id").value;
    const payload = {
      category: $("budget-category").value,
      monthly_limit: Number($("budget-limit").value),
    };
    try {
      await (id ? updateBudget(id, payload) : createBudget(payload));
      closeModal("budget-modal");
      toast(id ? "Budget updated" : "Budget saved");
      await refresh();
    } catch (error) {
      reportError(error);
    }
  });
}
