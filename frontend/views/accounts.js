import { createAccount, listAccounts } from "../api/accounts.js";
import { bindModalClose, closeModal, openModal } from "../components/modal.js";
import { renderAccounts } from "../components/tables.js";
import { reportError, toast } from "../components/toast.js";
import { $ } from "../utils/dom.js";
import { getBaseCurrency } from "../utils/money.js";

export async function loadAccounts() {
  renderAccounts(await listAccounts(), $("accounts-full"));
}

function openAccountModal() {
  $("account-name").value = "";
  $("account-type").value = "checking";
  $("account-currency").value = getBaseCurrency();
  $("account-opening").value = "0";
  openModal("account-modal");
}

export function initAccountsView({ refresh }) {
  $("add-account-btn").addEventListener("click", openAccountModal);
  bindModalClose("close-account-modal", "account-modal");
  $("account-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await createAccount({
        name: $("account-name").value,
        type: $("account-type").value,
        currency: $("account-currency").value,
        opening_balance: Number($("account-opening").value),
      });
      closeModal("account-modal");
      toast("Account added");
      await refresh();
    } catch (error) {
      reportError(error);
    }
  });
}
