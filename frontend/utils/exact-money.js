// decimal-v1 wire values are converted to BigInt cents, never Number.
export function decimalToCents(value) {
  if (typeof value !== "string" || !/^-?(0|[1-9][0-9]*)\.[0-9]{2}$/.test(value)) {
    throw new Error("Expected a decimal-v1 money string");
  }
  const negative = value.startsWith("-");
  const [whole, fraction] = (negative ? value.slice(1) : value).split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction);
  return negative ? -cents : cents;
}

export function centsToDecimal(value) {
  if (typeof value !== "bigint") throw new Error("Expected BigInt cents");
  const absolute = value < 0n ? -value : value;
  return (value < 0n ? "-" : "") + String(absolute / 100n)
    + "." + String(absolute % 100n).padStart(2, "0");
}
