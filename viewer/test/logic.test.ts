import { test } from "node:test";
import assert from "node:assert/strict";
import { ADJUDICATION_STATES, bandText, boundaryText, byPosition, correctionBody, correctionText, decide, evidenceTarget, flagText, hasRecords, highlightText, label, newestOnly, NOT_CHECKED, overlayShown, periodText, recordBody, restateCommand, reReviewText, SELF_DECLARED, stepClaim, stepPage, whoText } from "../src/logic.ts";
import type { Entry, Version } from "../src/logic.ts";

test("the correction body leaves out empty optional fields", () => {
  const f = { value: " 5 ", unit: "", metric: "", period_label: "  ", contributor: "ann", capacity: "analyst", rationale: "typo" };
  assert.deepEqual(correctionBody(f), { value: "5", contributor: "ann", capacity: "analyst", rationale: "typo" });
});

test("a correction shows who, why and the value it replaced; a re-review entry names its kind, id and version", () => {
  assert.equal(correctionText({ contributor: "Ann", capacity: "analyst", rationale: "misread digit", replaced: { value_text: "1,100" } }),
               "Ann (analyst): misread digit; replaced 1,100");
  assert.equal(reReviewText({ kind: "period review", id: 3, version: 2 }), "period review #3 on version 2");
  // Story 5.2's adjudication entry names the other side, as correct.entry_text prints it.
  assert.equal(reReviewText({ kind: "adjudication", id: 4, version: 2, with: { claim: 9, version: 11 } }),
               "adjudication #4 on version 2 with claim 9 version 11");
});

const entry = (over: Partial<Entry>): Entry => ({
  id: 1, contributor: "Ana", organisation: "Acme audit", capacity: "head of sustainability", latest: true,
  outcome: "accepted", reviewed_on: "2025-06-30", scope: "Scope 1", conclusion: "verified", evidence_document: null,
  evidence_company: null, evidence_page: null, evidence_note: "ledger", evidence_state: null, evidence_deleted: null, ...over,
});
const version = (over: Partial<Version>): Version => ({
  id: 1, value_text: "1", unit_text: null, company_confirmations: [], auditor_reviews: [], disagreement: null,
  reviewer_flags: [], adjudications: [], highlights: [], ...over,
});

test("the disagreement band is shown exactly when the two ledgers disagree", () => {
  assert.equal(bandText(null), null);
  assert.equal(bandText({ company: ["accepted"], auditor: ["disputed"] }),
               "Company confirmation and auditor review disagree on this version: company accepted; auditor disputed.");
  assert.equal(bandText({ company: ["accepted", "rejected"], auditor: ["disputed"] }),
               "Company confirmation and auditor review disagree on this version: company accepted, rejected; auditor disputed.");
});

test("earlier entries are kept apart from each contributor's latest, never dropped", () => {
  const es = [entry({ id: 1, latest: false }), entry({ id: 2 }), entry({ id: 3, contributor: "Bob", latest: true })];
  const { latest, earlier } = byPosition(es);
  assert.deepEqual(latest.map((e) => e.id), [2, 3]);
  assert.deepEqual(earlier.map((e) => e.id), [1]);
  assert.equal(latest.length + earlier.length, es.length);
  assert.equal(whoText(es[0]), "Ana (Acme audit), head of sustainability");
  assert.equal(whoText({ ...es[0], organisation: null }), "Ana, head of sustainability");
});

test("the self-declared line goes on every claim with an entry of any kind, on any version", () => {
  assert.equal(hasRecords([version({})]), false);
  assert.equal(hasRecords([version({ auditor_reviews: [entry({})] }), version({ id: 2 })]), true);
  const h = { id: 1, claim_version: 1, contributor: "Ana", organisation: null, capacity: "c", latest: true, note: "n", evidence_deleted: null };
  assert.equal(hasRecords([version({}), version({ id: 2, highlights: [h] })]), true);
  assert.equal(SELF_DECLARED, "Identities and capacities are self-declared. GCT does not check them and does not adopt any conclusion as its own.");
});

test("an evidence link jumps only to an active workspace document", () => {
  assert.equal(evidenceTarget(entry({})), null); // a note only
  assert.deepEqual(evidenceTarget(entry({ evidence_document: 4, evidence_page: 7, evidence_state: "registered" })), { document: 4, page: 7 });
  assert.deepEqual(evidenceTarget(entry({ evidence_document: 4, evidence_state: "restored" })), { document: 4, page: 1 });
  assert.equal(evidenceTarget(entry({ evidence_document: 4, evidence_page: 7, evidence_state: "archived" })), null);
  assert.equal(evidenceTarget(entry({ evidence_document: 4, evidence_state: "registered", evidence_deleted: { document: 2, at: "t" } })), null);
});

test("highlights and flags are attributed to their contributor, never to GCT", () => {
  const who = { contributor: "Ana", organisation: "Acme audit", capacity: "c", latest: true };
  assert.equal(highlightText({ ...who, id: 1, claim_version: 3, note: "check the 2023 report", evidence_deleted: null }),
               "Highlighted by Ana (Acme audit) (self-declared): check the 2023 report");
  assert.equal(flagText({ ...who, id: 1, decision: "raised", rationale: "too good" }),
               "Potential greenwashing concern raised by Ana (Acme audit) (self-declared): too good");
  assert.equal(flagText({ ...who, organisation: null, id: 2, decision: "withdrawn", rationale: "explained" }),
               "Potential greenwashing concern withdrawn by Ana (self-declared): explained");
});

test("a review body keeps the contributor's text as typed and sends ids and pages as numbers", () => {
  assert.deepEqual(recordBody({ conclusion: "  We verified it ", evidence_note: " ", evidence_page: "3", version: "12" }, ["version", "evidence_page"]),
                   { conclusion: "  We verified it ", evidence_page: 3, version: 12 });
});

test("V3: no restatement state; the restatement command is offered to copy", () => {
  assert.deepEqual(ADJUDICATION_STATES.map(([k]) => k), ["explained-difference", "extraction-error", "reviewer-confirmed-issue", "evidence-not-found"]);
  assert.ok(!ADJUDICATION_STATES.some(([k, v]) => /restat/.test(k + v)));
  assert.equal(restateCommand(3, 8), 'gct restate record --original 3 --restated 8 --page N --quote "TEXT"');
});

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
