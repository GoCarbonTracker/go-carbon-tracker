import { test } from "node:test";
import assert from "node:assert/strict";
import { bar, chipText, choiceChip, choiceText, claimsButton, exists, existsText, fitName, kindText, KEPT_FILTER, limitText, NO_CHOICES, NO_VIEWS, NONE_IN_GRAPHS, NONE_IN_TABLES, type Question, questionCount, ready, removeLabel, removedLine, rowsButton, savedLine, savedText, SERIES_FROM_GRAPHS, SERIES_FROM_TABLES, seriesChip, seriesLabel, staleText } from "../src/transfer.ts";

const F = { company: [1] };
const claims = (n: number, version = 3) =>
  ({ type: "claims" as const, claim_ids: Array.from({ length: n }, (_, i) => i + 1), filter: F, data_version: version });
const series = { type: "series" as const, series_id: "s1", filter: F, data_version: 3 };

test("rows of Tables go to Graphs as claims or, when the server finds one series, as a time series", () => {
  assert.deepEqual(bar("tables", claims(3), 3, null), {
    claims: { label: "Show 3 rows in Graphs", enabled: true }, series: { label: "Show as a time series", enabled: true }, reason: null });
  assert.equal(bar("tables", claims(1), 3, null).claims.label, "Show 1 row in Graphs");
  assert.equal(bar("tables", claims(500), 3, null).claims.enabled, true); // the limit itself is drawn
});

test("claim nodes go to Tables as claims, a series node as its series", () => {
  assert.deepEqual(bar("graphs", claims(2), 3, null), {
    claims: { label: "Show 2 claims in Tables", enabled: true }, series: { label: "Show this series in Tables", enabled: false }, reason: null });
  assert.deepEqual(bar("graphs", series, 3, null), {
    claims: { label: "Show 0 claims in Tables", enabled: false }, series: { label: "Show this series in Tables", enabled: true }, reason: null });
});

// The D10 reasons, one case each; no transfer button is enabled with a reason shown.
test("D10: nothing selected", () => {
  for (const [from, text] of [["tables", NONE_IN_TABLES], ["graphs", NONE_IN_GRAPHS]] as const) {
    const b = bar(from, null, 3, null);
    assert.equal(b.reason, text);
    assert.ok(!b.claims.enabled && !b.series.enabled);
  }
  assert.equal(NONE_IN_TABLES, "Select rows to show them in Graphs.");
});

test("D10: more claims than the graph limit", () => {
  const b = bar("tables", claims(501), 3, null);
  assert.equal(b.reason, "501 rows selected; a graph draws at most 500. Select fewer.");
  assert.equal(b.claims.enabled, false);
  assert.equal(limitText(1200), "1,200 rows selected; a graph draws at most 500. Select fewer.");
});

test("D10: a time series of claims in no series or in several shows the server's reason, no chip", () => {
  const none = { data_version: 3, drawable: false, reason: "These claims are in no series: no metric key.", series: null };
  const two = { data_version: 3, drawable: false, reason: "These claims are in 2 series; pick one.", series: null };
  assert.equal(seriesChip(none, F, "Tables"), "These claims are in no series: no metric key.");
  assert.equal(seriesChip(two, F, "Tables"), "These claims are in 2 series; pick one.");
  const one = { data_version: 3, drawable: true, reason: null, series: { id: "s9", label: "Total Scope 1 emissions", metric_key: "ghg_scope_1" } };
  assert.deepEqual(seriesChip(one, F, "Tables"), {
    selection: { type: "series", series_id: "s9", filter: F, data_version: 3 }, text: "Time series: Total Scope 1 emissions from Tables" });
});

test("D10: a selection made on another data version", () => {
  const text = "Data version 3 is no longer the current one; the current version is 4. Reload to see version 4.";
  for (const b of [bar("tables", claims(2), 3, 4), bar("graphs", claims(2, 3), 4, null), bar("graphs", series, 3, 4)]) {
    assert.equal(b.reason, text);
    assert.ok(!b.claims.enabled && !b.series.enabled);
  }
  assert.equal(staleText(3, 4), text);
});

test("D10: a picked element that is not a claim or a series names its kind", () => {
  assert.equal(bar("graphs", { type: "none", kind: "page" }, 3, null).reason,
    "A page has no rows of its own; select claims or a series.");
  assert.equal(kindText("adjudication"), "An adjudication has no rows of its own; select claims or a series.");
  assert.equal(kindText("auditor review"), "An auditor review has no rows of its own; select claims or a series.");
  assert.equal(kindText("comparison edge"), "A comparison edge has no rows of its own; select claims or a series.");
  const b = bar("graphs", { type: "none", kind: "period" }, 3, null);
  assert.ok(!b.claims.enabled && !b.series.enabled);
});

test("a series picked with claims or with another series asks for one series or claims only", () => {
  const b = bar("graphs", { type: "none", kind: "series" }, 3, null); // graphs.ts picked() for both
  assert.equal(b.reason, "Select one series, or claims only.");
  assert.ok(!b.claims.enabled && !b.series.enabled);
});

test("the chip names the count or the series and where it came from; its button says what it removes", () => {
  assert.equal(chipText(claims(3), "Tables"), "3 claims from Tables");
  assert.equal(chipText(claims(1), "Graphs"), "1 claim from Graphs");
  assert.equal(chipText(series, "Graphs", "Total energy"), "Time series: Total energy from Graphs");
  assert.equal(removeLabel("3 claims from Tables"), "Remove the selection: 3 claims from Tables");
  assert.equal(claimsButton(1200), "Show 1,200 claims in Tables");
});

test("a series is named by its label or its metric in words, never by a stored key", () => {
  assert.equal(seriesLabel({ id: "s1", label: null, metric_key: "ghg_scope_1" }), "Scope 1 emissions");
  assert.equal(seriesLabel({ id: "s1", label: "ghg_scope_2" }), "Scope 2 emissions");
  assert.equal(seriesLabel({ id: "s1", label: null, metric_key: null }), "series s1");
});

test("the save form: an existing name is said first; saving needs a name and a key", () => {
  assert.ok(exists(" Scope 1 ", ["Scope 1"]) && !exists("scope 1", ["Scope 1"])); // names compare exactly
  assert.equal(existsText(" Scope 1 "), "A view named Scope 1 exists. Saving puts this one first and keeps the earlier one.");
  assert.ok(ready("a", "ana") && !ready(" ", "ana") && !ready("a", ""));
  assert.equal(savedText({ section: "graphs", saved_at: "2026-10-23T03:00:00Z", contributor: "Ana" }), "Graphs · saved 2026-10-23 by Ana");
});

test("the name box keeps 80 characters as the server counts them, not 80 UTF-16 units", () => {
  const e = "\u{1F600}"; // two UTF-16 units, one character
  assert.equal(fitName(e.repeat(80)), e.repeat(80));
  assert.equal(fitName(e.repeat(81)), e.repeat(80));
  assert.equal(fitName("a".repeat(81)), "a".repeat(80));
});

test("the existing-name check strips the name as the server's strip() does", () => {
  assert.ok(exists("\uFEFFAb", ["\uFEFFAb"]) && !exists("\uFEFFAb", ["Ab"])); // U+FEFF is not stripped
  assert.ok(exists("\u3000Ab\u0085", ["Ab"]));
  assert.equal(existsText("\uFEFFAb "), "A view named \uFEFFAb exists. Saving puts this one first and keeps the earlier one.");
});

const q = (key: string, matched: number, choices: Question["choices"] = []): Question =>
  ({ key, text: "?", filter: {}, section: "tables", matched, choices });

test("a question counts its claims on the version; metric-over-time counts its choices; 0 is shown", () => {
  assert.equal(questionCount(q("restated", 0), 7), "0 claims in data version 7");
  assert.equal(questionCount(q("different-values", 1), 7), "1 claim in data version 7");
  const c = { series: "s1", company: "Acme", label: "Total Scope 1 emissions", periods: 4, filter: { series: ["s1"] } };
  assert.equal(questionCount(q("metric-over-time", 85, [c, c]), 7), "2 series with two or more periods");
  assert.equal(choiceText(c), "Acme: Total Scope 1 emissions, 4 periods");
  assert.deepEqual(choiceChip(c, 7), { selection: { type: "series", series_id: "s1", filter: { series: ["s1"] }, data_version: 7 },
    text: "Time series: Total Scope 1 emissions from Questions" });
});

// AC 9: every text this file shows has no internal name, and none of GCT's own words claims a check it never made.
test("the texts carry no internal names and never say verified, assured, certified or compliant", () => {
  const c = { series: "s1", company: "Acme", label: null, periods: 2, filter: {} };
  const texts = [rowsButton(2), claimsButton(2), SERIES_FROM_TABLES, SERIES_FROM_GRAPHS, NONE_IN_TABLES, NONE_IN_GRAPHS,
    limitText(501), staleText(3, 4), kindText("boundary"), kindText("series"), chipText(claims(2), "Tables"), chipText(series, "Graphs", "x"),
    removeLabel("x"), KEPT_FILTER, NO_VIEWS, existsText("x"), savedText({ section: "tables", saved_at: "2026-10-23", contributor: "Ana" }),
    savedLine("x"), removedLine("x"), questionCount(q("restated", 2), 3), questionCount(q("metric-over-time", 0), 3),
    choiceText(c), NO_CHOICES];
  for (const t of texts) {
    assert.doesNotMatch(t, /\b[a-z]+_[a-z_]+\b|claim_ids|series_id|data_version|metric-over-time|\bgct\b|undefined|null|NaN/, t);
    assert.doesNotMatch(t, /verified|assured|certified|compliant/i, t);
  }
});
