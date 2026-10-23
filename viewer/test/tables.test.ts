import { test } from "node:test";
import assert from "node:assert/strict";
import { ariaSort, boundaryText, clearedText, COLUMNS, lastOffset, locationText, metricText, nextSort, pageCount, pageState, periodText, request, type Row, rowsText, rowTarget, selectionOf, selectLabel, spaced, togglePage, toggled, valueText } from "../src/tables.ts";

function row(over: { claim?: Partial<Row["claim"]>; evidence?: Partial<Row["evidence"]>; location?: Partial<Row["evidence"]["location"]> } = {}): Row {
  const claim: Row["claim"] = {
    id: 42, page: 3, sheet: null, cell: null, metric_text: "Total Scope 1 emissions", value_text: "1,234", unit_text: "tCO2e",
    period_label: "FY 2024-25", period: { kind: "fiscal_year", start: "2024-04-01", end: "2025-03-31", state: "accepted" },
    boundary: { value: "subsidiary_set", detail: "TMPVL, TPEML", state: "resolved" }, claim_state: "current", ...over.claim,
  };
  const location = { document: 7, page: 3, sheet: null, cell: null, claim_id: 42, resolved: true, reason: null, ...over.location };
  return {
    claim, company_name: "Acme", document_name: "acme-2025.pdf",
    evidence: { boxes: [[1, 2, 3, 4]], text: "matched", location, ...over.evidence },
    review: { text: "no review records" },
  };
}

test("stored words with an underscore are printed with spaces", () => {
  assert.equal(spaced("fiscal_year"), "fiscal year");
  assert.equal(spaced("as_at"), "as at");
  assert.equal(periodText(row()), "FY 2024-25 · 2024-04-01..2025-03-31 fiscal year (accepted)");
  assert.equal(boundaryText(row()), "subsidiary set: TMPVL, TPEML (resolved)");
  assert.equal(boundaryText(row({ claim: { boundary: { value: "standalone", detail: null, state: "accepted" } } })), "standalone (accepted)");
  assert.equal(periodText(row({ claim: { period_label: null, period: { kind: null, start: null, end: null, state: "unresolved" } } })),
    "unknown (unresolved)");
  assert.equal(periodText(row({ claim: { period: { kind: "as_at", start: "2025-03-31", end: "2025-03-31", state: "accepted" } } })),
    "FY 2024-25 · 2025-03-31..2025-03-31 as at (accepted)");
});

test("location, wording and value as the columns print them", () => {
  assert.equal(locationText(row()), "page 3");
  assert.equal(locationText(row({ location: { page: null, sheet: "Emissions", cell: "B4" } })), "sheet Emissions, cell B4");
  assert.equal(locationText(row({ location: { page: null, resolved: false, reason: "not on a page" } })), "no source location");
  assert.equal(metricText(row({ claim: { metric_text: null } })), "no metric wording");
  assert.equal(valueText(row()), "1,234 tCO2e");
  assert.equal(valueText(row({ claim: { unit_text: null } })), "1,234");
});

test("the row checkbox names the claim and the first 60 characters of its wording", () => {
  assert.equal(selectLabel(row({ claim: { metric_text: "x".repeat(999) } })), `Select claim 42: ${"x".repeat(60)}`);
  assert.equal(selectLabel(row({ claim: { metric_text: null } })), "Select claim 42: no metric wording");
});

test("GCT's own column words have no underscore and none of the words it never uses", () => {
  const own = [...COLUMNS.map((c) => c.name), periodText(row()), boundaryText(row()), clearedText("filter", 2),
    clearedText("version", 3), rowsText(0, 200, 15348)].join(" ");
  assert.doesNotMatch(own, /_|verified|assured|certified|compliant/i);
});

test("one sort key: ascending, descending, ascending; aria-sort only on the sorted header", () => {
  const a = nextSort(null, "value");
  const b = nextSort(a, "value");
  assert.deepEqual([a, b, nextSort(b, "value")], [{ key: "value", dir: "asc" }, { key: "value", dir: "desc" }, { key: "value", dir: "asc" }]);
  assert.deepEqual(nextSort(b, "company"), { key: "company", dir: "asc" });
  assert.deepEqual(COLUMNS.map((c) => ariaSort(b, c.key)).filter(Boolean), ["descending"]);
  assert.deepEqual(COLUMNS.map((c) => ariaSort(null, c.key)).filter(Boolean), []);
  assert.equal(COLUMNS.find((c) => c.name === "Review")!.key, null);
  assert.deepEqual(COLUMNS.map((c) => c.key).filter(Boolean),
    ["company", "document", "page", "metric", "value", "period", "boundary", "evidence", "state"]);
});

test("paging: 200 rows a page; Last asks the start of the last page", () => {
  assert.deepEqual([pageCount(200), lastOffset(200)], [1, 0]);
  assert.deepEqual([pageCount(201), lastOffset(201)], [2, 200]);
  assert.equal(rowsText(200, 1, 201), "Rows 201 to 201 of 201");
  assert.deepEqual([pageCount(15348), lastOffset(15348)], [77, 15200]);
  assert.equal(rowsText(15200, 148, 15348), "Rows 15,201 to 15,348 of 15,348");
  assert.equal(rowsText(0, 200, 15348), "Rows 1 to 200 of 15,348");
});

test("checks: one row, the rows of a page, and the header box state", () => {
  let s = toggled(new Set(), 5);
  assert.deepEqual([...s], [5]);
  assert.deepEqual([...toggled(s, 5)], []);
  assert.equal(pageState(s, [5, 6]), "some");
  s = togglePage(s, [5, 6]);
  assert.equal(pageState(s, [5, 6]), "all");
  assert.equal(pageState(togglePage(s, [5, 6]), [5, 6]), "none");
  const other = togglePage(toggled(new Set(), 1), [5, 6]); // a check on another page stays
  assert.deepEqual([...togglePage(other, [5, 6])], [1]);
});

test("the selection handed to 6.4 is F6's claims object, or null when nothing is checked", () => {
  assert.equal(selectionOf(new Set(), {}, 3), null);
  assert.deepEqual(selectionOf(new Set([9, 2, 5]), { company: [1] }, 3),
    { type: "claims", claim_ids: [2, 5, 9], filter: { company: [1] }, data_version: 3 });
  assert.equal(clearedText("filter", 3), "Selection cleared: the filter changed.");
  assert.equal(clearedText("version", 4), "Selection cleared: data version 4 is now shown.");
});

test("an incoming selection: claim ids ride with every request, a series replaces the filter's series", () => {
  assert.deepEqual(request({ company: [1] }, { key: "value", dir: "desc" }, null),
    { filter: { company: [1] }, extra: { sort: [{ key: "value", dir: "desc" }] } });
  assert.deepEqual(request({}, null, { type: "claims", claim_ids: [3, 4], filter: {}, data_version: 2 }),
    { filter: {}, extra: { sort: [], claim_ids: [3, 4] } });
  assert.deepEqual(request({ series: ["a", "b"], company: [1] }, null, { type: "series", series_id: "s1", filter: {}, data_version: 2 }),
    { filter: { series: ["s1"], company: [1] }, extra: { sort: [] } });
});

test("where a row's evidence opens", () => {
  assert.deepEqual(rowTarget(row(), 5), { document: 7, page: 3, claim_id: 42 }); // its box is drawn as selected
  assert.deepEqual(rowTarget(row({ evidence: { boxes: null } }), 5), { document: 7, page: 3 }); // the page only
  assert.deepEqual(rowTarget(row({ evidence: { boxes: [] } }), 5), { document: 7, page: 3 });
  assert.equal(rowTarget(row(), 2), null); // the page is beyond the document
  assert.equal(rowTarget(row({ location: { page: null, resolved: false, reason: "not on a page" } }), 5), null);
  assert.deepEqual(rowTarget(row({ location: { page: null, sheet: "acme-meter", cell: "B2" }, evidence: { boxes: null } }), 0),
    { document: 7, sheet: "acme-meter", cell: "B2" }); // the cell view, never the page endpoint
});
