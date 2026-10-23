import { test } from "node:test";
import assert from "node:assert/strict";
import { availableText, cellPath, countText, isCell, isEmpty, isStale, newerVersion, periodUnknownText, recordsBody, seriesText, toggle, withPeriod, withText } from "../src/records.ts";

test("a list value toggles on and off, and an emptied list is left out (an empty list is refused)", () => {
  const f = toggle(toggle({}, "company", 1), "company", 2);
  assert.deepEqual(f, { company: [1, 2] });
  assert.deepEqual(toggle(toggle(f, "company", 1), "company", 2), {});
  assert.ok(isEmpty(toggle(toggle({}, "review", "highlight"), "review", "highlight")));
});

test("text is cut at 200 characters and left out when empty", () => {
  assert.equal(withText({}, "x".repeat(250)).text!.length, 200);
  assert.deepEqual(withText({ text: "scope" }, ""), {});
});

test("a period keeps either end and is left out with neither", () => {
  const f = withPeriod({}, "from", "2024-04-01");
  assert.deepEqual(f, { period: { from: "2024-04-01" } });
  assert.deepEqual(withPeriod(withPeriod(f, "to", "2025-03-31"), "from", ""), { period: { to: "2025-03-31" } });
  assert.deepEqual(withPeriod(f, "from", ""), {});
});

test("every records request carries the pinned version", () => {
  assert.deepEqual(recordsBody({ metric: ["ghg_scope_1"] }, 3, "table", 0, 1),
    { filter: { metric: ["ghg_scope_1"] }, data_version: 3, shape: "table", offset: 0, limit: 1 });
});

test("the count line names the version", () => {
  assert.equal(countText(1, 2), "1 claim matches in data version 2.");
  assert.equal(countText(0, 2), "0 claims match in data version 2.");
  assert.equal(periodUnknownText(0), null);
  assert.equal(periodUnknownText(2), "2 claims with an unknown period are left out by the period.");
});

test("a newer current version is offered, the pinned one never", () => {
  assert.equal(newerVersion(3, 3), null);
  assert.equal(newerVersion(3, 4), 4);
  assert.equal(newerVersion(null, 1), 1);
  assert.equal(newerVersion(3, null), null);
  assert.equal(availableText(4), "Data version 4 is available.");
});

test("only the stale-pin refusal is stale", () => {
  assert.ok(isStale(409, "Data version 3 is no longer the current one; the current version is 4."));
  assert.ok(!isStale(409, "There is no published data version yet."));
  assert.ok(!isStale(400, "Data version 3 is no longer the current one; the current version is 4."));
});

test("a sheet and cell open the cell view, a page opens the Evidence section", () => {
  assert.ok(isCell({ document: 3, sheet: "meter", cell: "B2" }));
  assert.ok(!isCell({ document: 1, page: 4, claim_id: 9 }));
  assert.equal(cellPath({ document: 3, sheet: "a b", cell: "B2" }, 5), "/api/documents/3/cells?sheet=a%20b&cell=B2&data_version=5");
});

test("a series reads as company, metric, points and id", () => {
  assert.equal(seriesText({ id: "2b7f", metric_key: "ghg_scope_1", company_id: 1, points: 4 }, "Acme"),
    "Acme: Scope 1 emissions, 4 points (2b7f)");
  assert.equal(seriesText({ id: "x", metric_key: null, company_id: 1, points: 1 }, "Acme"), "Acme: no metric key, 1 point (x)");
});
