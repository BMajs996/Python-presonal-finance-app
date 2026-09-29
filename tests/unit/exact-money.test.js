import assert from "node:assert/strict";
import { test } from "node:test";
import { decimalToCents, centsToDecimal } from "../../frontend/utils/exact-money.js";

test("decimal-v1 round-trips transaction and statement limits and aggregates beyond safe integers", () => {
  for (const value of ["0.00", "0.01", "-0.01", "1000000000.00", "-1000000000.00",
    "90000000000000.00", "-90000000000000.00", "90071992547409.93",
    "-180000000000000.01", "92233720368547758.07"]) {
    const wire = JSON.parse(JSON.stringify({ amount: value }));
    assert.equal(centsToDecimal(decimalToCents(wire.amount)), value);
  }
  assert.equal(decimalToCents("90071992547409.93") + decimalToCents("0.01"), 9007199254740994n);
});

test("exact-money helpers reject approximate numbers and malformed decimal strings", () => {
  for (const value of [1.23, null, "1e3", "1.2", "1.234", "01.00", "NaN", " 1.00", "+1.00"]) {
    assert.throws(() => decimalToCents(value));
  }
  assert.throws(() => centsToDecimal(123));
});
