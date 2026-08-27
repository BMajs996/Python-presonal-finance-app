let baseCurrency = "USD";
const formatters = new Map();

export function setBaseCurrency(currency) {
  baseCurrency = currency || "USD";
}

export function getBaseCurrency() {
  return baseCurrency;
}

export function money(value, currency = baseCurrency) {
  if (!formatters.has(currency)) {
    formatters.set(currency, new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
    }));
  }
  return formatters.get(currency).format(Number(value || 0));
}
