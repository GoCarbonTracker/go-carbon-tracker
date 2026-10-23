// Pure Tables logic (story 6.2, the F3 table shape and F4 rows of docs/views.md), tested with `node --test`
// (Node strips the types): only types and logic.ts are imported.
import { decide, type Box } from "./logic.ts";
import type { EvidenceTarget, Filter, Selection } from "./records.ts";

/** The part of an F4 row the table shows (6.1 F11 d: the evidence and review texts come with the row). */
export type Row = {
  claim: {
    id: number; page: number | null; sheet: string | null; cell: string | null; metric_text: string | null;
    value_text: string; unit_text: string | null; period_label: string | null;
    period: { kind: string | null; start: string | null; end: string | null; state: string };
    boundary: { value: string; detail: string | null; state: string };
    claim_state: string;
  };
  company_name: string;
  document_name: string;
  evidence: {
    boxes: Box[] | null; text: string;
    location: { document: number; page: number | null; sheet: string | null; cell: string | null; claim_id: number | null;
      resolved: boolean; reason: string | null };
  };
  review: { text: string };
};

export const PAGE = 200;

export type Sort = { key: string; dir: "asc" | "desc" } | null;

/** The columns in order, with the F3 sort key of each sortable one (Review and the select column have none). */
export const COLUMNS: { name: string; key: string | null }[] = [
  { name: "Company", key: "company" }, { name: "Document", key: "document" }, { name: "Location", key: "page" },
  { name: "Metric wording", key: "metric" }, { name: "Value", key: "value" }, { name: "Period", key: "period" },
  { name: "Boundary", key: "boundary" }, { name: "Evidence", key: "evidence" }, { name: "Review", key: null },
  { name: "Claim state", key: "state" },
];

/** A stored word printed for people: fiscal_year reads "fiscal year". */
export function spaced(word: string): string {
  return word.replace(/_/g, " ");
}

export function locationText(r: Row): string {
  const l = r.evidence.location;
  if (l.sheet !== null && l.cell !== null) return `sheet ${l.sheet}, cell ${l.cell}`;
  return l.page !== null ? `page ${l.page}` : "no source location";
}

export function metricText(r: Row): string {
  return r.claim.metric_text ?? "no metric wording";
}

export function valueText(r: Row): string {
  return r.claim.unit_text ? `${r.claim.value_text} ${r.claim.unit_text}` : r.claim.value_text;
}

export function periodText(r: Row): string {
  const p = r.claim.period;
  const printed = r.claim.period_label ? `${r.claim.period_label} · ` : "";
  if (p.start === null) return `${printed}unknown (${p.state})`;
  return `${printed}${p.start}..${p.end}${p.kind ? ` ${spaced(p.kind)}` : ""} (${p.state})`;
}

export function boundaryText(r: Row): string {
  const b = r.claim.boundary;
  return `${spaced(b.value)}${b.detail ? `: ${b.detail}` : ""} (${b.state})`;
}

/** The row checkbox's label: the claim id and the start of its wording. */
export function selectLabel(r: Row): string {
  return `Select claim ${r.claim.id}: ${metricText(r).slice(0, 60)}`;
}

/** One key at a time: a new key sorts ascending, the same key flips. */
export function nextSort(now: Sort, key: string): Sort {
  return now?.key === key && now.dir === "asc" ? { key, dir: "desc" } : { key, dir: "asc" };
}

/** aria-sort for a header: only the sorted one carries it. */
export function ariaSort(now: Sort, key: string | null): "ascending" | "descending" | undefined {
  if (key === null || now?.key !== key) return undefined;
  return now.dir === "asc" ? "ascending" : "descending";
}

/** The offset Last asks for: the start of the last page of 200. */
export function lastOffset(matched: number): number {
  return matched === 0 ? 0 : Math.floor((matched - 1) / PAGE) * PAGE;
}

export function pageCount(matched: number): number {
  return Math.ceil(matched / PAGE);
}

const n = (x: number) => x.toLocaleString("en-US");

export function rowsText(offset: number, shown: number, matched: number): string {
  return `Rows ${n(offset + 1)} to ${n(offset + shown)} of ${n(matched)}`;
}

/** The filter and the extra request keys for an incoming F6 selection (6.1 F11 a): a claims selection sends its ids
 * with every request, a series selection sets the filter's series to that one series. */
export function request(filter: Filter, sort: Sort, selection?: Selection | null) {
  const f = selection?.type === "series" ? { ...filter, series: [selection.series_id] } : filter;
  return {
    filter: f,
    extra: { sort: sort ? [sort] : [], ...(selection?.type === "claims" ? { claim_ids: selection.claim_ids } : {}) },
  };
}

export function toggled(chosen: ReadonlySet<number>, id: number): Set<number> {
  const out = new Set(chosen);
  if (!out.delete(id)) out.add(id);
  return out;
}

/** How many of this page's rows are checked: the header checkbox is checked, indeterminate or clear. */
export function pageState(chosen: ReadonlySet<number>, ids: number[]): "all" | "some" | "none" {
  const on = ids.filter((i) => chosen.has(i)).length;
  return on === 0 ? "none" : on === ids.length ? "all" : "some";
}

/** The header checkbox: all of this page's rows checked clears them, otherwise checks them all. */
export function togglePage(chosen: ReadonlySet<number>, ids: number[]): Set<number> {
  const out = new Set(chosen);
  if (pageState(chosen, ids) === "all") ids.forEach((i) => out.delete(i));
  else ids.forEach((i) => out.add(i));
  return out;
}

/** The F6 selection handed to 6.4, or null when nothing is checked. */
export function selectionOf(chosen: ReadonlySet<number>, filter: Filter, version: number): Selection | null {
  if (chosen.size === 0) return null;
  return { type: "claims", claim_ids: [...chosen].sort((a, b) => a - b), filter, data_version: version };
}

export function clearedText(why: "filter" | "version", version: number): string {
  return why === "filter" ? "Selection cleared: the filter changed." : `Selection cleared: data version ${version} is now shown.`;
}

export const NO_LOCATION = "This claim has no source location to open.";

/** Where a row's evidence opens (FR47): a spreadsheet cell, a page with the claim selected when it has a box, the
 * page only without a box, or nothing (null) when there is no location or the page is outside the document. */
export function rowTarget(r: Row, pages: number): EvidenceTarget | null {
  const l = r.evidence.location;
  if (!l.resolved) return null;
  if (l.sheet !== null && l.cell !== null) return { document: l.document, sheet: l.sheet, cell: l.cell };
  const d = decide({ page: l.page, boxes: r.evidence.boxes }, pages);
  if (d === "do not navigate") return null;
  return d === "jump and highlight" ? { document: l.document, page: l.page, claim_id: r.claim.id } : { document: l.document, page: l.page };
}
