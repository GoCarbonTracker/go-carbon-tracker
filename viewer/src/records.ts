// Pure Tables-and-Graphs logic (story 6.1, the shared E6 contract in docs/views.md), tested with `node --test`
// (Node strips the types): no imports, no enums.

/** The filter object, version 1 (F1): every field optional; fields combine with AND, values in one list with OR. */
export type Filter = {
  company?: number[]; document?: number[]; metric?: string[]; text?: string; period?: { from?: string; to?: string };
  boundary?: string[]; claim_state?: string[]; evidence?: string[]; match?: string[]; series?: string[];
  comparison?: string[]; review?: string[]; source_kind?: string[];
};
export type ListField = "company" | "document" | "metric" | "boundary" | "claim_state" | "evidence" | "match" | "series"
  | "comparison" | "review" | "source_kind";

/** The fixed values of the worded fields, each with the words the filter bar shows (gct.stages.view.CHOICES). */
export const CHOICES: Record<string, [string, string][]> = {
  metric: [
    ["ghg_scope_1", "Scope 1 emissions"],
    ["ghg_scope_2_location", "Scope 2 (location-based)"], ["ghg_scope_2_market", "Scope 2 (market-based)"],
    ["ghg_scope_2", "Scope 2 emissions"],
    ["ghg_scope_1_2", "Scope 1 and 2 emissions"], ["ghg_scope_3", "Scope 3 emissions"],
    ["energy_total", "total energy"], ["energy_renewable", "renewable energy"],
    ["energy_non_renewable", "non-renewable energy"], ["water_withdrawal_total", "water withdrawal"],
    ["water_consumption_total", "water consumption"], ["water_discharge_total", "water discharge"],
    ["waste_total", "total waste"], ["unmapped", "no metric key"],
  ],
  source_kind: [["table", "table KPIs"], ["text", "narrative text"]],
  boundary: [["standalone", "standalone"], ["subsidiary_set", "subsidiary set"], ["consolidated", "consolidated"],
    ["segment", "segment"], ["unknown", "unknown"]],
  claim_state: [["current", "current"], ["not-found", "not found in the newest reading"],
    ["not-extracted", "page read again, not yet extracted"]],
  evidence: [["matched", "matched"], ["cited", "cited"], ["unresolved", "unresolved"], ["not-checked", "not checked"]],
  match: [["series", "in a series"], ["reviewed", "linked by review"], ["uncertain", "uncertain"],
    ["not-matchable", "not matchable"]],
  comparison: [["same", "same value"], ["restatement", "restatement"], ["unresolved", "unresolved conflict"],
    ["not-compared", "not compared"]],
  review: [["company-confirmation", "company confirmation"], ["auditor-review", "auditor review"],
    ["disagreement", "disagreement"], ["flag-raised", "flag raised"], ["highlight", "highlight"],
    ["needs-re-review", "needs renewed review"], ["corrected", "corrected"], ["adjudicated", "adjudicated"]],
};

/** The filter with one list value added or taken out; a list left empty is left out (an empty list is refused). */
export function toggle(f: Filter, field: ListField, value: string | number): Filter {
  const now = (f[field] ?? []) as (string | number)[];
  const next = now.includes(value) ? now.filter((v) => v !== value) : [...now, value];
  const out: Filter = { ...f };
  if (next.length === 0) delete out[field];
  else (out as Record<string, unknown>)[field] = next;
  return out;
}

/** One series of the values answer (F11 g). */
export type SeriesValue = { id: string; metric_key: string | null; company_id: number; points: number };

/** A series in the filter bar: whose, which metric, how many points, and its id (two series can share the rest). */
export function seriesText(s: SeriesValue, company: string): string {
  const metric = CHOICES.metric.find(([k]) => k === s.metric_key)?.[1] ?? s.metric_key ?? "no metric key";
  return `${company}: ${metric}, ${s.points} point${s.points === 1 ? "" : "s"} (${s.id})`;
}

export function withText(f: Filter, text: string): Filter {
  const out: Filter = { ...f };
  if (text === "") delete out.text;
  else out.text = text.slice(0, 200);
  return out;
}

/** One end of the period; a period with neither end is left out. */
export function withPeriod(f: Filter, end: "from" | "to", day: string): Filter {
  const period = { ...f.period };
  if (day === "") delete period[end];
  else period[end] = day;
  const out: Filter = { ...f };
  if (period.from === undefined && period.to === undefined) delete out.period;
  else out.period = period;
  return out;
}

export function isEmpty(f: Filter): boolean {
  return Object.keys(f).length === 0;
}

/** The body of POST /api/records: the filter and the pinned version, so a stale pin is refused (F2). */
export function recordsBody(f: Filter, pinned: number, shape = "table", offset = 0, limit = 200) {
  return { filter: f, data_version: pinned, shape, offset, limit };
}

/** H: the count line of the Tables and Graphs area. */
export function countText(matched: number, version: number): string {
  return matched === 1 ? `1 claim matches in data version ${version}.` : `${matched} claims match in data version ${version}.`;
}

export function periodUnknownText(n: number): string | null {
  if (n === 0) return null;
  return n === 1 ? "1 claim with an unknown period is left out by the period." : `${n} claims with an unknown period are left out by the period.`;
}

/** The version rule (F2, E6-D2): a current version other than the pinned one (or the first one built while none
 * was pinned) is offered, never mixed in. */
export function newerVersion(pinned: number | null, current: number | null): number | null {
  return current !== null && current !== pinned ? current : null;
}

export function availableText(version: number): string {
  return `Data version ${version} is available.`;
}

/** A 409 that refuses the pin because another version is now current. */
export function isStale(status: number, cause: string): boolean {
  return status === 409 && /^Data version \d+ is no longer the current one/.test(cause);
}

/** Where a source opens (F5 locations; F11 f): a page of a PDF, with the claim to select, or a spreadsheet cell. */
export type EvidenceTarget = { document: number; page?: number | null; claim_id?: number | null; sheet?: string | null; cell?: string | null };

/** F6: a selection handed between sections. */
export type Selection =
  | { type: "claims"; claim_ids: number[]; filter: Filter; data_version: number }
  | { type: "series"; series_id: string; filter: Filter; data_version: number };

/** The services a Tables or Graphs tab body receives from the shell (F11 f). */
export type BodyProps = {
  filter: Filter;
  dataVersion: number;
  openEvidence: (t: EvidenceTarget) => void;
  selection?: Selection | null;
  onSelectionChange?: (s: Selection | null) => void;
};

/** A cell target opens the cell view; anything else opens a page in the Evidence section. */
export function isCell(t: EvidenceTarget): boolean {
  return typeof t.sheet === "string" && typeof t.cell === "string";
}

export function cellPath(t: EvidenceTarget, pinned: number): string {
  return `/api/documents/${t.document}/cells?sheet=${encodeURIComponent(t.sheet ?? "")}&cell=${encodeURIComponent(t.cell ?? "")}&data_version=${pinned}`;
}
