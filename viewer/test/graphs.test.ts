import { test } from "node:test";
import assert from "node:assert/strict";
import { canvasLabel, claimLabel, degrees, elements, type GraphAnswer, type GraphNode, hyperedgeRows, hypergraph, layoutOf, type Location,
  neighbourhood, opening, picked, type Point, pointRow, positions, request, reasonText, type Row, type SeriesAnswer,
  SERIES_SOURCE, sideText, timeSeries } from "../src/graphs.ts";

const at = (document: number | null, page: number | null, claim_id: number | null = null): Location =>
  ({ document, page, sheet: null, cell: null, claim_id, resolved: page !== null, reason: null });
const nowhere = (reason: string, document: number | null = 1): Location =>
  ({ document, page: null, sheet: null, cell: null, claim_id: null, resolved: false, reason });

function row(id: number, o: { document?: number; page?: number | null; sheet?: string; period?: [string, string] | null;
  boundary?: string | null; series?: string | null; evidence?: string; key?: string | null; location?: Location } = {}): Row {
  const document = o.document ?? 1;
  const page = o.page === undefined ? 1 : o.page;
  const location = o.location ?? (o.sheet ? { document, page: null, sheet: o.sheet, cell: "B2", claim_id: id, resolved: true, reason: null }
    : at(document, page, id));
  const period = o.period === undefined ? ["2024-04-01", "2025-03-31"] : o.period;
  const boundary = o.boundary === undefined ? "subsidiary_set" : o.boundary;
  return {
    claim: { id, document, page: o.sheet ? null : page, sheet: o.sheet ?? null, cell: o.sheet ? "B2" : null,
      metric_text: "Total Scope 1 emissions", metric_key: o.key === undefined ? "ghg_scope_1" : o.key, value_text: `1,${id}00`,
      unit_text: "tCO2e", period: { known: period !== null, start: period?.[0] ?? null, end: period?.[1] ?? null },
      boundary: { known: boundary !== null, value: boundary ?? "unknown", detail: boundary ? "Beta Power" : null },
      series_id: o.series === undefined ? "s1" : o.series },
    company_name: "Acme", document_name: `report-${document}.pdf`,
    evidence: { location, text: o.evidence ?? "matched" }, review: { text: "no review records" },
  };
}

function claimNode(r: Row, outside = 0): GraphNode {
  return { id: `claim:${r.claim.id}`, kind: "claim", label: "server label", evidence: [r.evidence.location], row: r,
    outside_text: outside ? `${outside} related claim${outside === 1 ? "" : "s"} outside this selection` : null };
}

// Two claims on one page with one known period and boundary, compared with each other; the first also with a claim
// outside the selection; a company confirmation citing an archived document; one series.
const a = row(1), b = row(2);
const answer: GraphAnswer = {
  data_version: 3, matched: 2, drawable: true, reason: null,
  nodes: [
    claimNode(a, 1),
    { id: "page:1:1", kind: "page", label: "report-1.pdf p1", evidence: [at(1, 1)] },
    { id: "period:2024-04-01..2025-03-31", kind: "period", label: "2024-04-01..2025-03-31", evidence: [at(1, 1), at(1, 1)] },
    { id: "boundary:subsidiary_set:Beta Power", kind: "boundary", label: "subsidiary_set: Beta Power", evidence: [at(1, 1)] },
    { id: "series:s1", kind: "series", label: "ghg_scope_1", evidence: [] },
    { id: "company:4", kind: "company", label: "company confirmation: accepted", evidence: [nowhere("document archived", 9)],
      contributor: "Ana", outcome: "accepted", text: "verified against the meter log", evidence_note: null },
    claimNode(b),
  ],
  hyperedges: [
    { id: "hyperedge:1", claim: "claim:1", members: ["page:1:1", "period:2024-04-01..2025-03-31",
      "boundary:subsidiary_set:Beta Power", "series:s1", "company:4", "claim:2"] },
    { id: "hyperedge:2", claim: "claim:2", members: ["page:1:1", "period:2024-04-01..2025-03-31",
      "boundary:subsidiary_set:Beta Power", "series:s1", "claim:1"] },
  ],
  edges: [
    ...["page:1:1", "period:2024-04-01..2025-03-31", "boundary:subsidiary_set:Beta Power", "series:s1", "company:4"]
      .map((m) => ({ id: `claim:1>${m}`, kind: "member", source: "claim:1", target: m, state: null, reason: null, evidence: [a.evidence.location] })),
    ...["page:1:1", "period:2024-04-01..2025-03-31", "boundary:subsidiary_set:Beta Power", "series:s1"]
      .map((m) => ({ id: `claim:2>${m}`, kind: "member", source: "claim:2", target: m, state: null, reason: null, evidence: [b.evidence.location] })),
    { id: "comparison:1:2", kind: "comparison", source: "claim:1", target: "claim:2", state: "restatement", reason: null,
      evidence: [a.evidence.location, at(2, 4, 2)] },
  ],
};
const words = { ghg_scope_1: "Scope 1 emissions" };

test("the neighbourhood graph draws every node of the answer once, its member edges and its comparison edge", () => {
  const items = neighbourhood(answer, words);
  const nodes = items.filter((i) => i.group === "nodes");
  assert.deepEqual(nodes.map((i) => i.id), answer.nodes.map((n) => n.id)); // the claim nodes are the answer's, no other
  const edgesAt = degrees(items);
  assert.equal(edgesAt.get("page:1:1"), 2); // two claims on one page: one page node with two edges
  assert.equal(edgesAt.get("period:2024-04-01..2025-03-31"), 2);
  const comparison = items.find((i) => i.kind === "comparison")!;
  assert.equal(comparison.label, "restatement");
  assert.equal(items.find((i) => i.id === "claim:1>page:1:1")!.label, "printed on");
});

test("the hypergraph has one hub per claim joined to the claim and to the same shared member nodes", () => {
  const items = hypergraph(answer, words);
  const hubs = items.filter((i) => i.kind === "hub" && i.group === "nodes");
  assert.deepEqual(hubs.map((h) => h.id), ["hub:1", "hub:2"]);
  const hubEdges = items.filter((i) => i.kind === "hub" && i.group === "edges");
  assert.deepEqual(hubEdges.filter((e) => e.source === "hub:2").map((e) => e.target),
    ["claim:2", "page:1:1", "period:2024-04-01..2025-03-31", "boundary:subsidiary_set:Beta Power", "series:s1"]);
  assert.equal(items.filter((i) => i.id === "page:1:1").length, 1); // both hubs share one page node
  assert.equal(degrees(items).get("page:1:1"), 2);
  assert.ok(!items.some((i) => i.kind === "member")); // no claim-to-member edges in this view
  assert.equal(items.filter((i) => i.kind === "comparison").length, 1);
  const rows = hyperedgeRows(answer, items);
  assert.equal(rows[0].members.length, 5);
  assert.deepEqual(rows[1].compared.map((c) => [c.claim.id, c.edges.map((e) => e.id)]), [["claim:1", ["comparison:1:2"]]]);
  assert.equal(opening(rows[0].hub, new Map()).targets[0].target.claim_id, 1); // a hub opens its claim's source
});

test("labels are printed wording and plain words: no metric key, node id or underscore token", () => {
  const items = [...neighbourhood(answer, words), ...hypergraph(answer, words)];
  const label = (id: string) => items.find((i) => i.id === id)!.label;
  assert.equal(label("claim:1"), "Total Scope 1 emissions: 1,100 tCO2e (page 1 of report-1.pdf)");
  assert.equal(label("page:1:1"), "page 1 of report-1.pdf");
  assert.equal(label("period:2024-04-01..2025-03-31"), "2024-04-01 to 2025-03-31");
  assert.equal(label("boundary:subsidiary_set:Beta Power"), "subsidiary set: Beta Power");
  assert.equal(label("series:s1"), "series: Scope 1 emissions of Acme");
  assert.equal(label("company:4"), "company confirmation by Ana (self-declared): accepted");
  for (const i of items) {
    const text = [i.label, i.word, ...i.notes].join(" ");
    assert.doesNotMatch(text, /_|ghg_scope|claim:|page:\d|period:|boundary:|series:s|hub:|%|score/, text);
    assert.doesNotMatch(text.replace(/"[^"]*"/g, ""), /verified|assured|certified|compliant/i, text); // GCT's own words
  }
  // contributor text only in quotation marks with its author
  assert.deepEqual(items.find((i) => i.id === "company:4")!.notes,
    ['Ana wrote: "verified against the meter log"', "the cited document is archived"]);
});

test("a claim compared with a claim outside the selection says so on its node and row", () => {
  const c = neighbourhood(answer, words).find((i) => i.id === "claim:1")!;
  assert.ok(c.notes.includes("1 related claim outside this selection"));
  assert.match(elements([c])[0].data.label, /1 related claim outside this selection/);
});

test("an unknown period and boundary are attributes in the claim's text, never nodes", () => {
  const r = row(7, { period: null, boundary: null, series: null });
  const one: GraphAnswer = { ...answer, matched: 1, edges: [], nodes: [claimNode(r), { id: "page:1:1", kind: "page", label: "", evidence: [at(1, 1)] }],
    hyperedges: [{ id: "hyperedge:7", claim: "claim:7", members: ["page:1:1"] }] };
  const items = neighbourhood(one, words);
  assert.deepEqual(items.map((i) => i.kind), ["claim", "page"]);
  assert.deepEqual(items[0].notes, ["matched", "period unknown", "boundary unknown"]);
});

test("a spreadsheet claim's cell node is named in words and opens the cell view's target", () => {
  const r = row(18, { sheet: "acme-meter", document: 3 });
  const g: GraphAnswer = { ...answer, matched: 1, edges: [],
    nodes: [claimNode(r), { id: "cell:3:acme-meter!B2", kind: "cell", label: "", evidence: [{ ...r.evidence.location, claim_id: null }] }],
    hyperedges: [{ id: "hyperedge:18", claim: "claim:18", members: ["cell:3:acme-meter!B2"] }] };
  const [claim, cell] = neighbourhood(g, words);
  assert.equal(cell.label, "sheet acme-meter cell B2 of report-3.pdf");
  assert.match(claim.label, /\(sheet acme-meter cell B2 of report-3\.pdf\)$/);
  assert.deepEqual(opening(cell, new Map()).targets[0].target, { document: 3, sheet: "acme-meter", cell: "B2" });
});

test("what opening an element does: one target, both sides of a comparison, or the words why nothing opens", () => {
  const items = neighbourhood(answer, words);
  const names = new Map([[1, "report-1.pdf"], [2, "report-2.pdf"]]);
  const get = (id: string) => items.find((i) => i.id === id)!;
  assert.deepEqual(opening(get("claim:1"), names), { targets: [{ text: "page 1 of report-1.pdf",
    target: { document: 1, page: 1, claim_id: 1 } }], say: null });
  assert.deepEqual(opening(get("period:2024-04-01..2025-03-31"), names).targets.map((t) => t.target), [{ document: 1, page: 1, claim_id: null }]);
  assert.deepEqual(opening(get("comparison:1:2"), names).targets.map((t) => t.text), ["page 1 of report-1.pdf", "page 4 of report-2.pdf"]);
  assert.deepEqual(opening(get("series:s1"), names), { targets: [], say: SERIES_SOURCE });
  assert.deepEqual(opening(get("company:4"), names), { targets: [], say: "the cited document is archived" });
  // NFR16: an unresolved or not-checked source with no page opens nothing and says why
  const lost = row(9, { location: { ...nowhere("unresolved: no such figure on the page"), claim_id: 9 }, evidence: "unresolved: no such figure on the page" });
  const node = neighbourhood({ ...answer, nodes: [claimNode(lost)], edges: [], hyperedges: [{ id: "h", claim: "claim:9", members: [] }] }, words)[0];
  assert.match(node.label, /\(report-1\.pdf\)$/); // no page invented
  assert.ok(node.notes.includes("unresolved: no such figure on the page"));
  assert.deepEqual(opening(node, names), { targets: [], say: "unresolved: no such figure on the page" });
  assert.equal(reasonText("document deleted"), "the cited document was deleted");
});

function point(id: number, document: number, order: number, period: [string, string], comparable = true): Point {
  return { ...row(id, { document, period }), period_order: order, period_start: period[0], period_end: period[1],
    comparable, not_comparable_reason: comparable ? null : "a different unit family" };
}
const FY24: [string, string] = ["2023-04-01", "2024-03-31"], FY25: [string, string] = ["2024-04-01", "2025-03-31"];
const series: SeriesAnswer = {
  data_version: 3, matched: 4, drawable: true, reason: null,
  series: { id: "s1", label: null, metric_key: "ghg_scope_1", company_name: "Acme" },
  points: [point(6, 2, 0, FY24), point(2, 1, 0, FY24), point(5, 2, 0, FY24, false), point(1, 1, 1, FY25)],
  comparisons: [
    { claim_a: 2, claim_b: 5, period_start: FY24[0], period_end: FY24[1], state: "restatement", reason: null, evidence: [at(1, 1, 2), at(2, 1, 5)] },
    { claim_a: 2, claim_b: 6, period_start: FY24[0], period_end: FY24[1], state: "unresolved conflict", reason: null, evidence: [at(1, 1, 2), at(2, 1, 6)] },
  ],
};

test("time-series positions: a column per period, a row per document, points of one period and document stacked", () => {
  const p = positions(series.points);
  assert.equal(p.get(2)!.x, p.get(6)!.x); // a restatement in a later report sits in the original's column
  assert.notEqual(p.get(2)!.y, p.get(6)!.y); // in another row
  assert.ok(p.get(1)!.x > p.get(2)!.x);
  assert.equal(p.get(1)!.y, p.get(2)!.y); // one row per document
  assert.equal(p.get(5)!.x, p.get(6)!.x);
  assert.ok(p.get(6)!.y > p.get(5)!.y); // stacked by claim id
  assert.ok(p.get(5)!.y > p.get(2)!.y); // document 2's row is below document 1's
  assert.deepEqual(positions(series.points), p); // a pure function
});

test("the time series has one node per point and one edge per comparison with its state word; tables match", () => {
  const items = timeSeries(series);
  assert.deepEqual(items.filter((i) => i.group === "nodes").map((i) => i.claim), [6, 2, 5, 1]);
  const edges = items.filter((i) => i.group === "edges");
  assert.deepEqual(edges.map((e) => [e.source, e.target, e.label]),
    [["point:2", "point:5", "restatement"], ["point:2", "point:6", "unresolved conflict"]]);
  assert.match(elements(edges)[1].classes, /unresolved/);
  assert.equal(items[0].label, "1,600 tCO2e\n2023-04-01 to 2024-03-31\nreport-2.pdf");
  assert.deepEqual(pointRow(series.points[2]), { period: "2023-04-01 to 2024-03-31", value: "1,500 tCO2e",
    document: "report-2.pdf", where: "page 1", comparable: "not comparable: a different unit family" });
  assert.equal(sideText(series.points[1]), "1,200 tCO2e, page 1 of report-1.pdf");
  assert.deepEqual(opening(items[0], new Map()).targets[0].target, { document: 2, page: 1, claim_id: 6 }); // F11 c
  assert.ok(elements(items).every((e) => e.group === "edges" || e.position));
});

test("S5b: claims, one series, another kind or nothing as the selection handed to the shell", () => {
  const items = neighbourhood(answer, words);
  const get = (id: string) => items.find((i) => i.id === id)!;
  assert.equal(picked([]), null);
  assert.deepEqual(picked([get("claim:2"), get("claim:1")]), { type: "claims", claim_ids: [1, 2] });
  assert.deepEqual(picked([get("series:s1")]), { type: "series", series_id: "s1" });
  assert.deepEqual(picked([get("page:1:1")]), { type: "none", kind: "page" });
  assert.deepEqual(picked([get("claim:1"), get("comparison:1:2")]), { type: "none", kind: "comparison edge" });
  assert.deepEqual(picked(timeSeries(series).slice(0, 2)), { type: "claims", claim_ids: [2, 6] });
});

test("one request per view: the graph shape for both graphs, the series shape for the time series, and the selection", () => {
  const f = { company: [1], series: ["old"] };
  assert.deepEqual(request(f, "neighbourhood"), { filter: f, shape: "graph" });
  assert.deepEqual(request(f, "hypergraph"), request(f, "neighbourhood")); // switching draws from the same answer
  assert.equal(request(f, "series").shape, "series");
  assert.deepEqual(request(f, "hypergraph", { type: "claims", claim_ids: [4, 5] }), { filter: f, shape: "graph", claim_ids: [4, 5] });
  assert.deepEqual(request(f, "neighbourhood", { type: "series", series_id: "s9" }),
    { filter: { company: [1], series: ["s9"] }, shape: "series" });
  assert.equal(canvasLabel(1, 3), "Graph of 1 claim in data version 3; every node and edge is in the tables below");
  assert.equal(claimLabel(row(3, { page: 2 })), "Total Scope 1 emissions: 1,300 tCO2e (page 2 of report-1.pdf)");
});

test("a location with neither page nor cell opens nothing (F11 i3)", () => {
  const i = neighbourhood(answer, words).find((x) => x.id === "claim:1")!;
  assert.deepEqual(opening({ ...i, locations: [{ ...at(1, 1, 1), page: null }] }, new Map()).targets, []);
});

test("cose up to 250 nodes, breadthfirst above (S2, measured), the time series by its positions", () => {
  const nodes = (n: number) => Array.from({ length: n }, (_, k) => ({ id: `n${k}`, group: "nodes" as const, kind: "claim",
    word: "claim", label: "", notes: [], locations: [] }));
  assert.equal(layoutOf("neighbourhood", nodes(250)), "cose");
  assert.equal(layoutOf("hypergraph", nodes(251)), "breadthfirst");
  assert.equal(layoutOf("series", nodes(600)), "preset");
});
