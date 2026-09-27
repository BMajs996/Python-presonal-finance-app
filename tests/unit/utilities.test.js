import assert from "node:assert/strict";
import { test } from "node:test";
import { execFileSync } from "node:child_process";
import { csvValue, csvText, parseCsv } from "../../frontend/utils/csv.js";
import { escapeHtml, escapeAttr, transactionClass } from "../../frontend/utils/escape.js";
import { money, compactMoney, setBaseCurrency } from "../../frontend/utils/money.js";
import { isIsoDate, validateDateRange } from "../../frontend/utils/dates.js";

test("CSV round-trips commas, quotes, multiline text and empty cells", () => {
  const row = ["2026-09-25", 'A "quoted", category', "line one\nline two", "", "€12"];
  assert.deepEqual(parseCsv(row.map(csvValue).join(",")), [row]);
  assert.deepEqual(parseCsv("a,b\r\n1,2\r\n\r\n"), [["a", "b"], ["1", "2"]]);
  assert.equal(csvValue(null), "");
});

test("HTML and attribute escaping covers every delimiter without executing markup", () => {
  assert.equal(escapeHtml('<img src="x" onerror=\'alert(1)\'>&'),
    "&lt;img src=&quot;x&quot; onerror=&#039;alert(1)&#039;&gt;&amp;");
  assert.equal(escapeAttr('" autofocus onfocus="alert(1)'), "&quot; autofocus onfocus=&quot;alert(1)");
  assert.equal(escapeHtml(null), "");
});

test("currency formatting follows Intl, explicit currency and invalid-number behavior", () => {
  const locale = globalThis.navigator?.languages?.[0] || globalThis.navigator?.language;
  const expected = (value, currency, options = {}) => new Intl.NumberFormat(locale,
    { style: "currency", currency, currencyDisplay: "symbol", ...options }).format(value);
  setBaseCurrency("EUR");
  assert.equal(money(1234.56), expected(1234.56, "EUR"));
  assert.equal(money(-12.34, "USD"), expected(-12.34, "USD"));
  assert.equal(compactMoney(12000, "USD"), expected(12000, "USD", { notation: "compact", maximumFractionDigits: 1 }));
  assert.equal(money("invalid"), "--");
  assert.equal(money(Infinity), "--");
  setBaseCurrency("USD");
});

test("calendar dates reject impossible dates and reversed ranges", () => {
  assert.equal(isIsoDate("2024-02-29"), true);
  for (const value of ["2026-02-29", "2026-04-31", "2026-13-01", "not-a-date"]) {
    assert.equal(isIsoDate(value), false);
  }
  assert.doesNotThrow(() => validateDateRange("2026-01-01", "2026-01-01"));
  assert.doesNotThrow(() => validateDateRange("", ""));
  assert.throws(() => validateDateRange("2026-09-30", "2026-09-01"), /Start date/);
});

for (const zone of ["Europe/Belgrade", "America/Los_Angeles", "Pacific/Kiritimati"]) {
  test("local dates remain correct across midnight in " + zone, () => {
    execFileSync(process.execPath, ["--input-type=module", "-e", `
      import assert from "node:assert/strict";
      import { todayIso, isIsoDate } from "./frontend/utils/dates.js";
      const NativeDate = Date;
      for (const instant of ["2026-01-01T00:30:00Z", "2026-01-01T23:30:00Z"]) {
        globalThis.Date = class extends NativeDate {
          constructor(...args) { super(...(args.length ? args : [instant])); }
        };
        const now = new NativeDate(instant);
        const expected = now.getFullYear() + "-" + String(now.getMonth()+1).padStart(2,"0")
          + "-" + String(now.getDate()).padStart(2,"0");
        assert.equal(todayIso(), expected);
        assert.equal(isIsoDate("2026-09-25"), true);
      }
    `], { env: { ...process.env, TZ: zone } });
  });
}


test("CSV text export neutralizes spreadsheet formulas without changing numeric cells", () => {
  for (const value of ["=1+1", "+SUM(A1)", "-1+1", "@SUM(A1)", "  =1", "\t=1", "\r\n=1"]) {
    assert.deepEqual(parseCsv(csvText(value)), [["'" + value]]);
  }
  assert.deepEqual(parseCsv(csvText('=HYPERLINK("https://example.com","x")')), [[
    '\'=HYPERLINK("https://example.com","x")'
  ]]);
  assert.equal(csvText("Ordinary text"), "Ordinary text");
  assert.equal(csvValue(-12.34), "-12.34");
  assert.equal(csvValue(12.34), "12.34");
});

test("CSV parsing bounds rows and rejects incomplete quoted fields", () => {
  assert.deepEqual(parseCsv("header\nrow", 2), [["header"], ["row"]]);
  assert.throws(() => parseCsv("header\nrow\nextra", 2), /limit/);
  assert.throws(() => parseCsv("header\nrow\nextra\n", 2), /limit/);
  assert.throws(() => parseCsv('header\n"unfinished'), /unterminated/);
});

test("transaction CSS classes use an allowlist", () => {
  assert.equal(transactionClass("income"), "income");
  assert.equal(transactionClass("expense"), "expense");
  assert.equal(transactionClass('income" onclick="alert(1)'), "");
  assert.equal(transactionClass(null), "");
});
