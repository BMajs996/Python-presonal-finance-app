import assert from "node:assert/strict";
import { test } from "node:test";
import { request } from "../../frontend/api/client.js";

test("API client returns JSON and handles empty deletion responses", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ items: [], total: 0 }));
  assert.deepEqual(await request("/api/transactions"), { items: [], total: 0 });
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 204 }));
  assert.equal(await request("/api/transactions/1", { method: "DELETE" }), null);
});

test("API client reports domain, validation, non-JSON and network errors", async (t) => {
  for (const [response, message] of [
    [Response.json({ detail: "Account not found" }, { status: 404 }), /Account not found/],
    [Response.json({ detail: [{ msg: "Amount required" }] }, { status: 422 }), /Amount required/],
    [new Response("Unavailable", { status: 503 }), /Request failed/],
  ]) {
    t.mock.method(globalThis, "fetch", async () => response);
    await assert.rejects(request("/api/accounts"), message);
  }
  t.mock.method(globalThis, "fetch", async () => { throw new TypeError("Network offline"); });
  await assert.rejects(request("/api/accounts"), /Network offline/);
});
