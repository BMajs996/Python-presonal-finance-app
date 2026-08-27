import { getMonthlyReport } from "../api/reports.js";
import { renderReportCharts } from "../components/charts.js";
import { reportError } from "../components/toast.js";
import { $ } from "../utils/dom.js";
import { money, setBaseCurrency } from "../utils/money.js";

export async function loadReports() {
  const data = await getMonthlyReport($("report-months").value);
  setBaseCurrency(data.currency);
  $("report-income").textContent = money(data.summary.income);
  $("report-expenses").textContent = money(data.summary.expenses);
  $("report-net").textContent = money(data.summary.net);
  $("report-savings").textContent = `${data.summary.savings_rate}%`;
  renderReportCharts(data);
}

export function initReportsView() {
  $("report-months").addEventListener("change", () => loadReports().catch(reportError));
}
