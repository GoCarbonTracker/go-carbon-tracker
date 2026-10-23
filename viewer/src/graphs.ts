// Pure Graphs-tab logic (story 6.3): a records answer (docs/views.md, the graph and series shapes) to the one element
// list the canvas and the tables are both drawn from, with labels in printed wording and plain words, and where each
// element's source opens. Tested with `node --test` (Node strips the types): no imports, no enums.

/** Where a source opens (docs/views.md "location"); resolved false means it cannot, and reason says why. */
export type Location = { document: number | null; page: number | null; sheet: string | null; cell: string | null;
  claim_id: number | null; resolved: boolean; reason: string | null };

type Known = { known: boolean };
/** The F4 row of a claim, as far as the Graphs tab reads it. */
export type Row = {
  claim: { id: number; document: number; page: number | null; sheet: string | null; cell: string | null;
    metric_text: string | null; metric_key: string | null; value_text: string; unit_text: string | null;
    period: Known & { start: string | null; end: string | null }; boundary: Known & { value: string; detail: string | null };
    series_id: string | null };
  company_name: string; document_name: string;
  evidence: { location: Location; text: string };
  review: { text: string };
};
export type GraphNode = { id: string; kind: string; label: string; evidence: Location[]; row?: Row;
  outside_text?: string | null; contributor?: string; outcome?: string | null; text?: string | null;
  evidence_note?: string | null };
export type GraphEdge = { id: string; kind: string; source: string; target: string; state: string | null;
  reason: string | null; evidence: Location[] };
export type Hyperedge = { id: string; claim: string; members: string[] };
export type GraphAnswer = { data_version: number; matched: number; drawable: boolean; reason: string | null;
  nodes: GraphNode[]; edges: GraphEdge[]; hyperedges: Hyperedge[] };
export type Point = Row & { period_order: number; period_start: string; period_end: string; comparable: boolean;
  not_comparable_reason: string | null };
export type SeriesComparison = { claim_a: number; claim_b: number; period_start: string; period_end: string;
  state: string; reason: string | null; evidence: Location[] };
export type SeriesAnswer = { data_version: number; matched: number; drawable: boolean; reason: string | null;
  series: { id: string; label: string | null; metric_key: string | null; company_name: string } | null;
  points: Point[]; comparisons: SeriesComparison[] };

/** One drawn element: a node or an edge, with everything its canvas mark and its table row show. */
export type Item = {
  id: string; group: "nodes" | "edges"; kind: string; word: string; label: string; notes: string[];
  source?: string; target?: string; state?: string | null; locations: Location[];
  claim?: number; series?: string; position?: { x: number; y: number };
};

export const VIEWS = [["neighbourhood", "Neighbourhood"], ["hypergraph", "Hypergraph"], ["series", "Time series"]] as const;
export type View = (typeof VIEWS)[number][0];

/** Kind words, printed in the tables and the legend (node kinds differ by shape and word, never by colour alone). */
export const WORDS: Record<string, string> = {
  claim: "claim", page: "page", cell: "cell", period: "period", boundary: "boundary", series: "series",
  company: "company confirmation", auditor: "auditor review", flag: "flag", highlight: "highlight",
  adjudication: "adjudication", hub: "hub", point: "point", member: "member", comparison: "comparison",
};

export const LEGEND = "Shapes: a claim is a circle; a page or cell a square; a period a rounded rectangle; a boundary "
  + "a hexagon; a series a diamond; a review record a triangle; an adjudication a pentagon; a hub a small dot (a hub "
  + "joins one claim to the items it is linked to). A comparison edge prints its state: an unresolved conflict is "
  + "dashed, not compared is dotted. Double-click a node or an edge, or press Enter on its row, to open its source. "
  + "Point at or select a node to read its whole label; zoom in to see the others.";

export const SERIES_SOURCE = "A series groups claims; open one of its claims to see its source.";

const BOUNDARIES: Record<string, string> = { standalone: "standalone", subsidiary_set: "subsidiary set",
  consolidated: "consolidated" };

function unit(r: Row): string {
  return r.claim.unit_text ? `${r.claim.value_text} ${r.claim.unit_text}` : r.claim.value_text;
}

/** Where a claim was read, in words: a page or a cell of its document, or the document alone. */
export function whereText(r: Row): string {
  const l = r.evidence.location;
  if (l.resolved && l.sheet !== null) return `sheet ${l.sheet} cell ${l.cell} of ${r.document_name}`;
  if (l.resolved && l.page !== null) return `page ${l.page} of ${r.document_name}`;
  return r.document_name;
}

export function claimLabel(r: Row): string {
  return `${r.claim.metric_text ?? "(no wording)"}: ${unit(r)} (${whereText(r)})`;
}

export function periodWords(start: string, end: string): string {
  return start === end ? `as at ${end}` : `${start} to ${end}`;
}

function boundaryWords(b: Row["claim"]["boundary"]): string {
  return `${BOUNDARIES[b.value] ?? b.value}${b.detail ? `: ${b.detail}` : ""}`;
}

/** What a claim says besides its label: its evidence text, its review text when it has records, an unknown period
 * or boundary (an attribute, never a node) and the related claims outside the selection. */
function claimNotes(r: Row, outside: string | null | undefined): string[] {
  const out = [r.evidence.text];
  if (r.review.text !== "no review records") out.push(r.review.text);
  if (!r.claim.period.known) out.push("period unknown");
  if (!r.claim.boundary.known) out.push("boundary unknown");
  if (outside) out.push(outside);
  return out;
}

const CITED: Record<string, string> = { "document archived": "the cited document is archived",
  "document deleted": "the cited document was deleted", "document not active": "the cited document is not active" };

/** Why a location does not open, in words. */
export function reasonText(reason: string | null): string {
  return (reason && CITED[reason]) ?? reason ?? "unresolved";
}

const RECORDS: Record<string, string> = { company: "company confirmation", auditor: "auditor review" };

function quoted(who: string | undefined, text: string | null | undefined): string[] {
  return text ? [`${who ?? "the contributor"} wrote: "${text}"`] : [];
}

/** A node's label and notes. The claim row of the first claim linked to a member node names its document, period,
 * boundary or series in words. Contributor text appears only in quotation marks with its author. */
function nodeItem(n: GraphNode, rowOf: Map<string, Row>, metricWords: Record<string, string>): Item {
  const r = n.row ?? rowOf.get(n.id);
  const item: Item = { id: n.id, group: "nodes", kind: n.kind, word: WORDS[n.kind] ?? n.kind, label: "", notes: [],
    locations: n.evidence };
  const who = `${n.contributor} (self-declared)`;
  const cited = n.evidence.filter((l) => !l.resolved).map((l) => reasonText(l.reason));
  if (n.kind === "claim" && n.row) {
    item.label = claimLabel(n.row);
    item.notes = claimNotes(n.row, n.outside_text);
    item.claim = n.row.claim.id;
  } else if (n.kind === "page" && r) {
    item.label = `page ${n.evidence[0]?.page} of ${r.document_name}`;
  } else if (n.kind === "cell" && r) {
    item.label = `sheet ${n.evidence[0]?.sheet} cell ${n.evidence[0]?.cell} of ${r.document_name}`;
  } else if (n.kind === "period" && r) {
    item.label = periodWords(r.claim.period.start!, r.claim.period.end!);
  } else if (n.kind === "boundary" && r) {
    item.label = boundaryWords(r.claim.boundary);
  } else if (n.kind === "series" && r) {
    // A mapped series has no label of its own (the answer then gives its metric key): it is named in words.
    const key = r.claim.metric_key;
    item.label = n.label !== key ? `series: ${n.label}`
      : `series: ${(key && metricWords[key]) ?? "no metric key"} of ${r.company_name}`;
    item.series = r.claim.series_id ?? undefined;
  } else if (n.kind in RECORDS) {
    item.label = `${RECORDS[n.kind]} by ${who}: ${n.outcome}`;
    item.notes = [...quoted(n.contributor, n.text), ...(n.evidence_note ? [`evidence note: "${n.evidence_note}"`] : []),
      ...cited];
  } else if (n.kind === "flag") {
    item.label = `flag ${n.outcome} by ${who}`;
    item.notes = quoted(n.contributor, n.text);
  } else if (n.kind === "highlight") {
    item.label = `highlight by ${who}`;
    item.notes = quoted(n.contributor, n.text);
  } else if (n.kind === "adjudication") {
    item.label = `adjudication: ${n.outcome}`;
    item.notes = [`recorded by ${who}`, ...quoted(n.contributor, n.text), ...cited];
  } else {
    item.label = WORDS[n.kind] ?? "item";
  }
  if (n.kind === "period" || n.kind === "boundary") item.notes = [...new Set(cited)];
  return item;
}

function rowsOfMembers(a: GraphAnswer): Map<string, Row> {
  const rows = new Map(a.nodes.filter((n) => n.row).map((n) => [n.id, n.row!]));
  const out = new Map<string, Row>();
  for (const h of a.hyperedges) for (const m of h.members) if (!out.has(m)) out.set(m, rows.get(h.claim)!);
  return out;
}

const RELATIONS: Record<string, string> = { page: "printed on", cell: "read from", period: "for the period",
  boundary: "with the boundary", series: "a point of", company: "confirmed in", auditor: "reviewed in",
  flag: "flagged in", highlight: "highlighted in", adjudication: "adjudicated in" };

/** A comparison edge is labelled with its state; a member edge with the relation word of what it links to. */
function edgeItem(e: GraphEdge, nodes: Map<string, Item>): Item {
  const comparison = e.kind === "comparison";
  const label = comparison ? `${e.state}${e.reason ? `: ${e.reason}` : ""}` : RELATIONS[nodes.get(e.target)!.kind] ?? "linked to";
  return { id: e.id, group: "edges", kind: e.kind, word: WORDS[e.kind] ?? e.kind, label, notes: [], source: e.source,
    target: e.target, state: comparison ? e.state : null, locations: e.evidence };
}

/** The neighbourhood graph (Q20's pairwise projection): every node of the answer, its member and comparison edges. */
export function neighbourhood(a: GraphAnswer, metricWords: Record<string, string> = {}): Item[] {
  const rowOf = rowsOfMembers(a);
  const nodes = a.nodes.map((n) => nodeItem(n, rowOf, metricWords));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return [...nodes, ...a.edges.map((e) => edgeItem(e, byId))];
}

/** The hypergraph (E6-D1): one hub per hyperedge joined to its claim and to each of its members, which are the same
 * shared nodes as the neighbourhood view; comparison edges join the claim nodes as there. */
export function hypergraph(a: GraphAnswer, metricWords: Record<string, string> = {}): Item[] {
  const items = neighbourhood(a, metricWords).filter((i) => i.group === "nodes" || i.kind === "comparison");
  const byId = new Map(items.map((i) => [i.id, i]));
  for (const h of a.hyperedges) {
    const claim = byId.get(h.claim)!;
    const hub = `hub:${claim.claim}`;
    items.push({ id: hub, group: "nodes", kind: "hub", word: WORDS.hub, label: "", notes: [], locations: claim.locations,
      claim: claim.claim });
    for (const m of [h.claim, ...h.members.filter((x) => !x.startsWith("claim:"))])
      items.push({ id: `${hub}>${m}`, group: "edges", kind: "hub", word: WORDS.hub, label: m === h.claim ? "hub of" : "joins",
        notes: [], source: hub, target: m, state: null, locations: claim.locations });
  }
  return items;
}

/** The Hyperedges table: each hub with its claim, its members and the comparison edges to its compared claims. */
export function hyperedgeRows(a: GraphAnswer, items: Item[]) {
  const byId = new Map(items.map((i) => [i.id, i]));
  const comparisons = items.filter((i) => i.kind === "comparison");
  return a.hyperedges.map((h) => {
    const claim = byId.get(h.claim)!;
    return { hub: byId.get(`hub:${claim.claim}`)!, claim,
      members: h.members.filter((m) => !m.startsWith("claim:")).map((m) => byId.get(m)!),
      compared: h.members.filter((m) => m.startsWith("claim:")).map((m) => ({ claim: byId.get(m)!,
        edges: comparisons.filter((e) => [e.source, e.target].includes(h.claim) && [e.source, e.target].includes(m)) })) };
  });
}

/** An edge's relation in the Edges table: a comparison's, or the relation word of what a member edge links to. */
export function relationText(i: Item): string {
  return i.kind === "comparison" ? "compared with" : i.label;
}

/** The name of an edge's row button: both ends, the relation and the kind, so no two edges of a claim sound alike. */
export function edgeName(i: Item, byId: Map<string, Item>): string {
  return `${byId.get(i.source!)?.label} ${relationText(i)} ${byId.get(i.target!)?.label} (${i.word} edge)`;
}

/** Number of edges at each node of a view, for the Nodes table. */
export function degrees(items: Item[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const i of items) if (i.group === "edges") for (const end of [i.source!, i.target!]) out.set(end, (out.get(end) ?? 0) + 1);
  return out;
}

export const COLUMN = 240;
export const ROW = 90;

/** Time-series positions (GR4): x by period order, one row per document in the order the documents first appear,
 * points of one period and one document stacked by claim id. No value axis. */
export function positions(points: Point[]): Map<number, { x: number; y: number }> {
  const docs: number[] = [];
  const stacks = new Map<string, number[]>();
  for (const p of [...points].sort((a, b) => a.period_order - b.period_order || a.claim.id - b.claim.id)) {
    if (!docs.includes(p.claim.document)) docs.push(p.claim.document);
    const k = `${p.claim.document}|${p.period_order}`;
    stacks.set(k, [...(stacks.get(k) ?? []), p.claim.id].sort((a, b) => a - b));
  }
  const height = new Map(docs.map((d) => [d, Math.max(...[...stacks].filter(([k]) => k.startsWith(`${d}|`)).map(([, v]) => v.length))]));
  const top = new Map<number, number>();
  let y = 0;
  for (const d of docs) {
    top.set(d, y);
    y += height.get(d)! * ROW + ROW / 2;
  }
  const out = new Map<number, { x: number; y: number }>();
  for (const p of points) {
    const at = stacks.get(`${p.claim.document}|${p.period_order}`)!.indexOf(p.claim.id);
    out.set(p.claim.id, { x: p.period_order * COLUMN, y: top.get(p.claim.document)! + at * ROW });
  }
  return out;
}

/** The time series: one node per point at its position, one edge per comparison row with its state word. */
export function timeSeries(a: SeriesAnswer): Item[] {
  const at = positions(a.points);
  const nodes: Item[] = a.points.map((p) => ({ id: `point:${p.claim.id}`, group: "nodes", kind: "point", word: WORDS.point,
    label: `${unit(p)}\n${periodWords(p.period_start, p.period_end)}\n${p.document_name}`,
    notes: [p.evidence.text, p.comparable ? "comparable" : `not comparable: ${p.not_comparable_reason}`],
    locations: [p.evidence.location], claim: p.claim.id, position: at.get(p.claim.id) }));
  const edges: Item[] = a.comparisons.map((c) => ({ id: `comparison:${c.claim_a}:${c.claim_b}`, group: "edges",
    kind: "comparison", word: WORDS.comparison, label: `${c.state}${c.reason ? `: ${c.reason}` : ""}`, notes: [],
    source: `point:${c.claim_a}`, target: `point:${c.claim_b}`, state: c.state, locations: c.evidence }));
  return [...nodes, ...edges];
}

/** A point in the Points table: period, value and unit as printed, document, where, comparable or its reason. */
export function pointRow(p: Point) {
  return { period: periodWords(p.period_start, p.period_end), value: unit(p), document: p.document_name,
    where: p.evidence.location.resolved ? whereText(p).replace(` of ${p.document_name}`, "") : reasonText(p.evidence.location.reason),
    comparable: p.comparable ? "comparable" : `not comparable: ${p.not_comparable_reason}` };
}

/** A side of a comparison in the Comparisons table. */
export function sideText(p: Point | undefined): string {
  return p ? `${unit(p)}, ${whereText(p)}` : "";
}

/** What opening an element does: the targets it opens (a chooser when there are several), or the words saying why
 * nothing opens (NFR16). A location that cannot open is never replaced by an invented page. */
export type Target = { document: number; page?: number | null; claim_id?: number | null; sheet?: string | null; cell?: string | null };
export function opening(i: Item, names: Map<number, string>): { targets: { text: string; target: Target }[]; say: string | null } {
  if (i.kind === "series") return { targets: [], say: SERIES_SOURCE };
  const seen = new Set<string>();
  const targets: { text: string; target: Target }[] = [];
  for (const l of i.locations) {
    if (!l.resolved || l.document === null || (l.page === null && l.sheet === null)) continue;
    const target: Target = l.sheet !== null ? { document: l.document, sheet: l.sheet, cell: l.cell }
      : { document: l.document, page: l.page, claim_id: l.claim_id };
    const key = JSON.stringify(target);
    if (seen.has(key)) continue;
    seen.add(key);
    const name = names.get(l.document) ?? `document ${l.document}`;
    targets.push({ text: l.sheet !== null ? `sheet ${l.sheet} cell ${l.cell} of ${name}` : `page ${l.page} of ${name}`, target });
  }
  if (targets.length > 0) return { targets, say: null };
  const why = [...new Set(i.locations.map((l) => reasonText(l.reason)))];
  return { targets: [], say: why.length ? why.join("; ") : "This item cites no source location." };
}

/** S5b: the F6 selection of the picked elements: claims, one series, a kind with no selection type, or none. */
export type Picked = { type: "claims"; claim_ids: number[] } | { type: "series"; series_id: string }
  | { type: "none"; kind: string } | null;
export function picked(items: Item[]): Picked {
  if (items.length === 0) return null;
  const odd = items.find((i) => i.kind !== "claim" && i.kind !== "point");
  if (!odd) return { type: "claims", claim_ids: items.map((i) => i.claim!).sort((a, b) => a - b) };
  if (items.length === 1 && odd.series) return { type: "series", series_id: odd.series };
  return { type: "none", kind: odd.group === "edges" ? `${odd.word} edge` : odd.word };
}

/** What a view asks (S1, S5b; the body is records.ts's recordsBody, F11 i4): the graph shape for the two graph
 * views, the series shape for the time series; an incoming claims selection limits it with claim_ids, a series
 * selection asks the series shape of that series (replacing the filter's series list). */
export function request(filter: Record<string, unknown>, view: View,
  selection?: { type: string; claim_ids?: number[]; series_id?: string } | null):
  { filter: Record<string, unknown>; shape: "graph" | "series"; claim_ids?: number[] } {
  if (selection?.type === "series") return { filter: { ...filter, series: [selection.series_id] }, shape: "series" };
  const shape = view === "series" ? "series" : "graph";
  return selection?.type === "claims" ? { filter, shape, claim_ids: selection.claim_ids } : { filter, shape };
}

/** Document names by id, from the rows of an answer. */
export function documentNames(rows: Row[]): Map<number, string> {
  return new Map(rows.map((r) => [r.claim.document, r.document_name]));
}

/** The canvas's label (S4). */
export function canvasLabel(claims: number, version: number): string {
  return `Graph of ${claims} claim${claims === 1 ? "" : "s"} in data version ${version}; every node and edge is in the tables below`;
}

/** S2: cose held headless Chrome for 1.5 s at 283 nodes and 2.2 s at 334 (docs/views.md, Graphs), so a graph of more
 * than COSE_LIMIT nodes is laid out by breadthfirst; the time series always by its own positions. Built-ins only. */
export const COSE_LIMIT = 250;
export function layoutOf(view: View, items: Item[]): "preset" | "cose" | "breadthfirst" {
  if (view === "series") return "preset";
  return items.filter((i) => i.group === "nodes").length > COSE_LIMIT ? "breadthfirst" : "cose";
}

/** Cytoscape's element list from the same items the tables show. */
export function elements(items: Item[]) {
  return items.map((i) => ({
    group: i.group,
    data: { id: i.id, label: i.group === "nodes" ? [i.label, ...i.notes.filter((n) => n !== "matched")].join("\n") : i.label,
      ...(i.group === "edges" ? { source: i.source, target: i.target } : {}) },
    classes: [i.kind, i.state === "unresolved conflict" ? "unresolved" : "", i.state === "not compared" ? "not-compared" : ""]
      .filter(Boolean).join(" "),
    ...(i.position ? { position: i.position } : {}),
  }));
}
