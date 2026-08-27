import { $ } from "../utils/dom.js";
import { money } from "../utils/money.js";

const charts = new Map();

function replaceChart(id, configuration) {
  charts.get(id)?.destroy();
  charts.set(id, new globalThis.Chart($(id), configuration));
}

const currencyAxis = {
  ticks: { callback: (value) => money(value) },
};

export function renderDashboardCharts(data) {
  replaceChart("balance-chart", {
    type: "line",
    data: {
      labels: data.balance_history.map((item) => item.date),
      datasets: [{
        label: "Balance",
        data: data.balance_history.map((item) => item.balance),
        borderWidth: 2,
        tension: 0.35,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: currencyAxis },
    },
  });

  replaceChart("expense-chart", {
    type: "doughnut",
    data: {
      labels: data.expense_categories.map((item) => item.category),
      datasets: [{ data: data.expense_categories.map((item) => item.total), borderWidth: 0 }],
    },
    options: { responsive: true, plugins: { legend: { position: "bottom" } } },
  });
}

export function renderReportCharts(data) {
  const labels = data.months.map((item) => item.month);
  replaceChart("monthly-chart", {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Income", data: data.months.map((item) => item.income), backgroundColor: "#15966d" },
        { label: "Expenses", data: data.months.map((item) => item.expenses), backgroundColor: "#d94b58" },
      ],
    },
    options: { responsive: true, scales: { y: { ...currencyAxis, beginAtZero: true } } },
  });

  const colors = ["#3b63f3", "#15966d", "#d94b58", "#e7a62b", "#725ac1"];
  replaceChart("category-trend-chart", {
    type: "line",
    data: {
      labels,
      datasets: data.category_trends.map((series, index) => ({
        label: series.category,
        data: series.totals,
        borderColor: colors[index % colors.length],
        backgroundColor: colors[index % colors.length],
        tension: 0.3,
      })),
    },
    options: { responsive: true, scales: { y: { ...currencyAxis, beginAtZero: true } } },
  });

  replaceChart("net-worth-chart", {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Balance",
        data: data.months.map((item) => item.balance),
        borderColor: "#3b63f3",
        backgroundColor: "rgba(59, 99, 243, .12)",
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: currencyAxis },
    },
  });
}
