export function csvValue(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function csvText(value) {
  const text = String(value ?? "");
  return csvValue(/^\s*[=+@-]/.test(text) ? "'" + text : text);
}

export function parseCsv(text, maxRows = Infinity) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    const next = text[index + 1];
    if (quoted && character === '"' && next === '"') {
      cell += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (!quoted && character === ",") {
      row.push(cell);
      cell = "";
    } else if (!quoted && (character === "\n" || character === "\r")) {
      if (character === "\r" && next === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      if (rows.length > maxRows) throw new Error(`CSV exceeds the ${maxRows - 1} transaction limit`);
      row = [];
      cell = "";
    } else {
      cell += character;
    }
  }

  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  if (rows.length > maxRows) throw new Error(`CSV exceeds the ${maxRows - 1} transaction limit`);
  if (quoted) throw new Error("CSV contains an unterminated quoted field");
  return rows;
}
