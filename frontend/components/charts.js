import { $ } from "../utils/dom.js";
import { compactMoney, money } from "../utils/money.js";

const charts = new Map();

function replaceChart(id, configuration) {
  charts.get(id)?.destroy();
  charts.set(id, new globalThis.Chart($(id), configuration));
}

const currencyAxis = {
  ticks: { callback: (value) => compactMoney(value) },
  grid: { color: "rgba(116, 128, 148, .14)" },
};

const currencyTooltip = {
  callbacks: {
    label: (context) => `${context.dataset.label || context.label}: ${money(context.raw)}`,
  },
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
        borderColor: "#3b63f3",
        backgroundColor: "rgba(59, 99, 243, .08)",
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.35,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      interaction: { intersect: false, mode: "index" },
      plugins: { legend: { display: false }, tooltip: currencyTooltip },
      scales: { y: currencyAxis },
    },
  });

  const hasExpenses = data.expense_categories.length > 0;
  replaceChart("expense-chart", {
    type: "doughnut",
    data: {
      labels: hasExpenses
        ? data.expense_categories.map((item) => item.category)
        : ["No expenses"],
      datasets: [{
        label: "Expenses",
        data: hasExpenses
          ? data.expense_categories.map((item) => item.total)
          : [1],
        backgroundColor: hasExpenses
          ? ["#3b63f3", "#15966d", "#d94b58", "#e7a62b", "#725ac1", "#2b879e"]
          : ["#e5e9f0"],
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      cutout: "66%",
      plugins: {
        legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } },
        tooltip: hasExpenses ? currencyTooltip : { enabled: false },
      },
    },
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
    options: {
      responsive: true,
      plugins: { tooltip: currencyTooltip },
      scales: { y: { ...currencyAxis, beginAtZero: true } },
    },
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
    options: {
      responsive: true,
      plugins: { tooltip: currencyTooltip },
      scales: { y: { ...currencyAxis, beginAtZero: true } },
    },
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
      plugins: { legend: { display: false }, tooltip: currencyTooltip },
      scales: { y: currencyAxis },
    },
  });
}
