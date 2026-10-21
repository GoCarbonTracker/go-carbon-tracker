import { test } from "node:test";
import assert from "node:assert/strict";
import { boundaryText, decide, label, newestOnly, NOT_CHECKED, overlayShown, periodText, stepClaim, stepPage } from "../src/logic.ts";

test("published period dates are shown with the printed label, never unknown", () => {
  const resolved = { period_label: null, period_kind: "calendar_year", period_start: "2024-01-01", period_end: "2024-12-31", period_state: "resolved" };
  assert.equal(periodText(resolved), "2024-01-01..2024-12-31 calendar_year (resolved)");
  assert.equal(periodText({ ...resolved, period_label: "FY24", period_kind: "fiscal_year", period_start: "2023-04-01",
                            period_end: "2024-03-31", period_state: "accepted" }), "FY24 · 2023-04-01..2024-03-31 fiscal_year (accepted)");
  const proposed = { period_label: "FY24", period_kind: null, period_start: null, period_end: null, period_state: "proposed" };
  assert.equal(periodText(proposed), "FY24 · unknown (proposed)");
  assert.equal(periodText({ ...proposed, period_label: null, period_state: "extracted" }), "unknown (extracted)");
});

test("the boundary carries its state", () => {
  assert.equal(boundaryText({ reporting_boundary: "standalone", boundary_detail: "Acme Ltd", boundary_state: "accepted" }),
               "standalone: Acme Ltd (accepted)");
  assert.equal(boundaryText({ reporting_boundary: "unknown", boundary_detail: null, boundary_state: "proposed" }),
               "unknown (proposed)");
});

test("a late answer for an earlier selection is dropped", async () => {
  const requests = newestOnly();
  const shown: string[] = [];
  const answer = (doc: string, ms: number) => {
    const id = requests.start();
    return new Promise<void>((done) =>
      setTimeout(() => {
        if (requests.isCurrent(id)) shown.push(doc);
        done();
      }, ms),
    );
  };
  // Document A is clicked first and answers last; document B is clicked second and answers first.
  await Promise.all([answer("A", 30), answer("B", 5)]);
  assert.deepEqual(shown, ["B"]);
});

test("the overlay waits for its own image", () => {
  const p1 = "/api/documents/1/pages/1.png?scale=1.5";
  const p2 = "/api/documents/1/pages/2.png?scale=1.5";
  assert.equal(overlayShown(null, p1), false);
  assert.equal(overlayShown(p1, p2), false); // page 2 asked for, page 1's image still the last loaded
  assert.equal(overlayShown(p2, p2), true);
  assert.equal(overlayShown(p2, "/api/documents/2/pages/2.png?scale=1.5"), false);
});

test("three source-match labels with their reasons verbatim, and not checked as a plain null", () => {
  const matched = label("matched", null);
  const cited = label("cited", "no box");
  const unresolved = label("unresolved", "page not read: gct read");
  assert.deepEqual(matched, { status: "matched", text: "matched" });
  assert.deepEqual(cited, { status: "cited", text: "cited: no box" });
  assert.deepEqual(unresolved, { status: "unresolved", text: "unresolved: page not read: gct read" });
  assert.equal(new Set([matched.status, cited.status, unresolved.status]).size, 3);
  assert.deepEqual(label(null, null), { status: null, text: NOT_CHECKED });
  assert.equal(NOT_CHECKED, "not checked: run gct link");
});

test("V3: jump and highlight, jump only, do not navigate", () => {
  const box: [number, number, number, number] = [10, 20, 30, 40];
  assert.equal(decide({ page: 2, boxes: [box] }, 3), "jump and highlight");
  assert.equal(decide({ page: 2, boxes: null }, 3), "jump only");
  assert.equal(decide({ page: 2, boxes: [] }, 3), "jump only");
  assert.equal(decide({ page: null, boxes: null }, 3), "do not navigate");
  assert.equal(decide({ page: 999, boxes: [box] }, 3), "do not navigate");
  assert.equal(decide({ page: 0, boxes: null }, 3), "do not navigate");
});

test("page steps stay within the document", () => {
  assert.equal(stepPage(1, -1, 3), 1);
  assert.equal(stepPage(1, 1, 3), 2);
  assert.equal(stepPage(3, 1, 3), 3);
});

test("claim steps move through the list and stop at its ends", () => {
  assert.equal(stepClaim(-1, 1, 4), 0);
  assert.equal(stepClaim(-1, -1, 4), 3);
  assert.equal(stepClaim(0, -1, 4), 0);
  assert.equal(stepClaim(2, 1, 4), 3);
  assert.equal(stepClaim(3, 1, 4), 3);
  assert.equal(stepClaim(-1, 1, 0), -1);
});
