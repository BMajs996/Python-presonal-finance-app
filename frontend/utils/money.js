let baseCurrency = "USD";
const formatters = new Map();
const locale = globalThis.navigator?.languages?.[0] || globalThis.navigator?.language;

export function setBaseCurrency(currency) {
  baseCurrency = currency || "USD";
}

export function getBaseCurrency() {
  return baseCurrency;
}

export function money(value, currency = baseCurrency, options = {}) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "--";

  const normalizedCurrency = (currency || baseCurrency).toUpperCase();
  const key = JSON.stringify([locale, normalizedCurrency, options]);
  if (!formatters.has(key)) {
    formatters.set(key, new Intl.NumberFormat(locale, {
      style: "currency",
      currency: normalizedCurrency,
      currencyDisplay: "symbol",
      ...options,
    }));
  }
  return formatters.get(key).format(amount);
}

export function compactMoney(value, currency = baseCurrency) {
  if (Math.abs(Number(value)) < 10_000) {
    return money(value, currency, { maximumFractionDigits: 0 });
  }
  return money(value, currency, {
    notation: "compact",
    maximumFractionDigits: 1,
  });
}
