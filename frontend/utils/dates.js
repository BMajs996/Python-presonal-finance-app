export function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export function isIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function validateDateRange(start, end) {
  if (start && !isIsoDate(start)) throw new Error("Invalid start date");
  if (end && !isIsoDate(end)) throw new Error("Invalid end date");
  if (start && end && start > end) throw new Error("Start date cannot be after end date");
}
